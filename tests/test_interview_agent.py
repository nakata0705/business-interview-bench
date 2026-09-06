"""MockLLM coverage for the real-model InterviewState adapter boundary."""

# The workspace resolver may not index the Inspect dev group or new siblings;
# project-level ``uv run pyright`` is authoritative for these tests.
# pyright: reportMissingImports=false

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from inspect_ai.model import ChatMessageAssistant, ModelOutput, get_model
from inspect_ai.tool import ToolCall

from business_interview_bench.interview_agent import (
    InterviewAgentError,
    InterviewStateAgent,
    candidate_id_for_utterance,
    load_checkpoint,
    render_interview_report,
)


def _candidate(utterance_id: str, *, support: str = "supports") -> dict[str, str]:
    return {
        "candidate_id": candidate_id_for_utterance(utterance_id),
        "semantic_support": support,
    }


def _agent(outputs: list[ModelOutput], **kwargs: Any) -> InterviewStateAgent:
    model = get_model(
        "mockllm/interview-state-agent-test",
        custom_outputs=outputs,
    )
    return InterviewStateAgent(model, max_tool_rounds=4, **kwargs)


class _RecordingModel:
    name = "recording-model"

    def __init__(self, outputs: list[ModelOutput]) -> None:
        self.outputs = list(outputs)
        self.inputs: list[Any] = []

    async def generate(self, input: Any, tools: Any, config: Any) -> ModelOutput:
        del tools, config
        self.inputs.append(list(input) if isinstance(input, list) else input)
        return self.outputs.pop(0)


def test_provider_tool_definitions_use_candidate_evidence_and_inline_refs() -> None:
    agent = _agent([ModelOutput.from_content("mockllm", "ack")])

    def assert_strict_objects(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                assert_strict_objects(item)
            return
        if not isinstance(value, dict):
            return
        properties = value.get("properties")
        if isinstance(properties, dict):
            assert set(value["required"]) == set(properties)
            assert value["additionalProperties"] is False
        for key, child in value.items():
            if key != "properties":
                assert_strict_objects(child)

    for definition in agent.tools:
        rendered = json.dumps(
            definition.parameters.model_dump(mode="json"),
            ensure_ascii=False,
        )
        assert "$defs" not in rendered
        assert "$ref" not in rendered
        assert definition.parameters.additionalProperties is False
        assert_strict_objects(definition.parameters.model_dump(mode="json"))

    record = next(item for item in agent.tools if item.name == "record_process_step")
    record_schema = record.parameters.model_dump(mode="json")
    evidence = record_schema["properties"]["evidence"]
    assert evidence["items"]["properties"]["candidate_id"]["type"] == "string"
    assert "start" not in evidence["items"]["properties"]

    revise = next(item for item in agent.tools if item.name == "revise_record")
    revise_schema = revise.parameters.model_dump(mode="json")
    assert "activity/condition" in revise_schema["properties"]["field"]["description"]
    assert revise_schema["properties"]["claim_status"]["enum"] == ["provisional"]
    assert revise_schema["properties"]["value"]["examples"][1]["id"] == "actor:sales"


def test_model_selected_tools_update_interview_state_from_public_text() -> None:
    text = "担当は営業で、申請書を確認します"
    agent = _agent(
        [
            ModelOutput.for_tool_call(
                "mockllm",
                "record_process_step",
                {
                    "step_id": "step:review",
                    "activity": {"state": "value", "value": "申請を確認"},
                    "actor": {"id": "actor:sales", "label": "営業"},
                    "inputs": {
                        "state": "value",
                        "items": [
                            {"id": "data:application", "label": "申請書"},
                        ],
                    },
                    "evidence": [_candidate("u1")],
                },
            ),
            ModelOutput.from_content(
                "mockllm", "記録しました。次に、他の担当者はいますか？"
            ),
            ModelOutput.for_tool_call(
                "mockllm",
                "complete_interview",
                {
                    "termination_reason": "the supplied short text is complete",
                    "content_completeness": "complete",
                },
            ),
        ]
    )

    result = asyncio.run(agent.run([text], complete=True))

    assert result.completed
    assert [item.tool_name for item in result.invocations] == [
        "record_process_step",
        "complete_interview",
    ]
    assert all(
        item.receipt is not None and item.receipt.ok for item in result.invocations
    )
    assert result.state.utterances[0].text == text
    step = result.state.business_model.process_steps[0]
    assert step.actor.entity_id == "actor:sales"
    assert step.inputs.entity_ids == ("data:application",)
    assert result.state.claims[0].evidence[0].quote == text
    assert candidate_id_for_utterance("u1") in agent.messages[1].text
    assert agent.metadata.execution_status == "completed"


def test_model_can_add_a_field_then_correct_it_in_conversation_order() -> None:
    first = "まず申請内容を確認します"
    second = "すみません、担当は営業です"
    agent = _agent(
        [
            ModelOutput.for_tool_call(
                "mockllm",
                "record_process_step",
                {
                    "step_id": "step:review",
                    "activity": {"state": "value", "value": "申請を確認"},
                    "evidence": [_candidate("u1")],
                },
            ),
            ModelOutput.from_content("mockllm", "次の発言を待ちます"),
            ModelOutput.for_tool_call(
                "mockllm",
                "revise_record",
                {
                    "record_id": "step:review",
                    "field": "actor",
                    "replacement_id": "claim:step:review:actor",
                    "statement": "担当は営業です。",
                    "value": {"id": "actor:sales", "label": "営業"},
                    "correction_note": "公開発言で担当者が判明した。",
                    "evidence": [_candidate("u2")],
                },
            ),
            ModelOutput.from_content("mockllm", "担当者を追記しました。"),
            ModelOutput.for_tool_call(
                "mockllm",
                "complete_interview",
                {"termination_reason": "short interview ended"},
            ),
        ]
    )

    result = asyncio.run(agent.run([first, second], complete=True))

    assert [item.tool_name for item in result.invocations] == [
        "record_process_step",
        "revise_record",
        "complete_interview",
    ]
    assert [item.id for item in result.state.utterances] == ["u1", "u2"]
    assert result.state.business_model.process_steps[0].actor.entity_id == "actor:sales"
    actor_claim = next(
        item
        for item in result.state.claims
        if item.predicate == "actor" and item.status != "rejected"
    )
    assert actor_claim.status == "provisional"
    assert actor_claim.evidence[0].utterance_id == "u2"


def test_unknown_candidate_and_confirmed_claim_are_rejected_without_state_change() -> (
    None
):
    text = "担当は営業です"
    agent = _agent(
        [
            ModelOutput.for_tool_call(
                "mockllm",
                "record_process_step",
                {
                    "step_id": "step:bad",
                    "activity": {"state": "value", "value": "確認"},
                    "claim_status": "confirmed",
                    "evidence": [{"candidate_id": "candidate:u99:full"}],
                },
            ),
            ModelOutput.for_tool_call(
                "mockllm",
                "record_process_step",
                {
                    "step_id": "step:good",
                    "activity": {"state": "value", "value": "確認"},
                    "evidence": [_candidate("u1")],
                },
            ),
            ModelOutput.from_content("mockllm", "公開発言に基づく暫定記録です。"),
        ]
    )

    turn = asyncio.run(agent.process_utterance(text))

    assert len(turn.invocations) == 2
    assert turn.invocations[0].receipt is None
    assert turn.invocations[0].error
    assert turn.invocations[1].receipt is not None
    assert turn.invocations[1].receipt.ok
    assert [item.id for item in agent.state.business_model.process_steps] == [
        "step:good"
    ]
    assert all(item.status == "provisional" for item in agent.state.claims)


def test_multiple_model_tool_calls_are_executed_in_declared_order() -> None:
    assistant = ChatMessageAssistant(
        content="",
        tool_calls=[
            ToolCall(
                id="call-step",
                function="record_process_step",
                arguments={
                    "step_id": "step:review",
                    "activity": {"state": "value", "value": "確認"},
                    "evidence": [_candidate("u1")],
                },
            ),
            ToolCall(
                id="call-flow",
                function="connect_process_steps",
                arguments={
                    "flow_id": "flow:review-to-sink",
                    "from_step_id": "step:review",
                    "to_step_id": "SINK",
                    "kind": "sink_boundary",
                    "evidence": [_candidate("u1")],
                },
            ),
        ],
    )
    agent = _agent(
        [
            ModelOutput.from_message(assistant, stop_reason="tool_calls"),
            ModelOutput.from_content("mockllm", "順番どおりに記録しました。"),
        ]
    )

    turn = asyncio.run(agent.process_utterance("申請を確認します"))

    assert [item.call_id for item in turn.invocations] == ["call-step", "call-flow"]
    assert all(
        item.receipt is not None and item.receipt.ok for item in turn.invocations
    )
    assert [item.id for item in agent.state.business_model.process_steps] == [
        "step:review"
    ]
    assert [item.id for item in agent.state.business_model.flows] == [
        "flow:review-to-sink"
    ]


def test_completion_tool_is_controller_gated_until_finish() -> None:
    agent = _agent(
        [
            ModelOutput.for_tool_call(
                "mockllm",
                "complete_interview",
                {"termination_reason": "premature"},
            ),
            ModelOutput.from_content("mockllm", "まだ公開発言を受け付けます。"),
            ModelOutput.for_tool_call(
                "mockllm",
                "complete_interview",
                {"termination_reason": "controller finished"},
            ),
        ]
    )

    turn = asyncio.run(agent.process_utterance("申請を確認します"))
    assert turn.invocations[0].receipt is None
    assert turn.invocations[0].error
    assert agent.state.completion.status == "active"

    final_turn = asyncio.run(agent.finish())
    assert final_turn is not None
    assert final_turn.invocations[0].receipt is not None
    assert agent.state.completion.status == "ended"


def test_truncated_output_does_not_execute_or_complete() -> None:
    agent = _agent(
        [ModelOutput.from_content("mockllm", "途中まで", stop_reason="max_tokens")]
    )

    with pytest.raises(InterviewAgentError) as caught:
        asyncio.run(agent.process_utterance("申請を確認します"))

    assert caught.value.kind == "output_truncated"
    assert agent.state.completion.status == "active"
    assert not agent.state.claims
    assert [message.role for message in agent.public_messages] == ["user"]
    assert agent.public_messages[0].content == "申請を確認します"
    assert "途中まで" not in agent.checkpoint().model_dump_json()
    assert agent.metadata.execution_status == "technical_failure"


def test_checkpoint_round_trip_preserves_public_question_for_short_answer(
    tmp_path: Path,
) -> None:
    question = "確認を担当するのは経理ですか？"
    first_model = _RecordingModel([ModelOutput.from_content("mockllm", question)])
    first_agent = InterviewStateAgent(first_model, max_tool_rounds=4)
    asyncio.run(first_agent.process_utterance("申請内容を確認する業務です。"))
    checkpoint_path = tmp_path / "interview.json"
    first_agent.save_checkpoint(checkpoint_path)

    resumed_model = _RecordingModel(
        [ModelOutput.from_content("mockllm", "了解しました")]
    )
    resumed = InterviewStateAgent.from_checkpoint_file(
        resumed_model,
        checkpoint_path,
        max_tool_rounds=4,
    )
    asyncio.run(resumed.process_utterance("はい"))

    input_messages = resumed_model.inputs[-1]
    question_index = next(
        index
        for index, message in enumerate(input_messages)
        if message.text == question
    )
    answer_index = next(
        index
        for index, message in enumerate(input_messages)
        if "utterance_id: u2" in message.text
    )
    assert question_index < answer_index
    assert "\nはい\n" in input_messages[answer_index].text


def test_checkpoint_round_trip_stores_public_conversation_without_provider_history(
    tmp_path: Path,
) -> None:
    first = "まず申請内容を確認します"
    first_agent = _agent(
        [
            ModelOutput.for_tool_call(
                "mockllm",
                "record_process_step",
                {
                    "step_id": "step:review",
                    "activity": {"state": "value", "value": "申請を確認"},
                    "evidence": [_candidate("u1")],
                },
            ),
            ModelOutput.from_content("mockllm", "記録しました"),
        ]
    )
    asyncio.run(first_agent.process_utterance(first))
    checkpoint_path = tmp_path / "interview.json"
    first_agent.save_checkpoint(checkpoint_path)

    checkpoint = load_checkpoint(checkpoint_path)
    assert checkpoint.schema_version == "business_interview.interview_agent.v3"
    assert checkpoint.next_utterance_number == 2
    assert checkpoint.metadata.prompt_version
    assert [message.role for message in checkpoint.public_messages] == [
        "user",
        "assistant",
    ]
    assert checkpoint.public_messages[0].utterance_id == "u1"
    assert checkpoint.public_messages[0].content == first
    assert checkpoint.public_messages[1].content == "記録しました"
    assert "messages" not in checkpoint.model_dump(mode="json")
    assert "turns" not in checkpoint.model_dump(mode="json")
    assert '"tool_calls":' not in checkpoint.model_dump_json()
    assert "assistant_text" not in checkpoint.model_dump_json()
    assert "api_key" not in checkpoint.model_dump_json().lower()
    restored_state = checkpoint.state

    resumed_model = _agent(
        [
            ModelOutput.for_tool_call(
                "mockllm",
                "revise_record",
                {
                    "record_id": "step:review",
                    "field": "actor",
                    "replacement_id": "claim:step:review:actor",
                    "statement": "担当は営業です。",
                    "value": {"id": "actor:sales", "label": "営業"},
                    "correction_note": "追加入力で担当者が判明した。",
                    "evidence": [_candidate("u2")],
                },
            ),
            ModelOutput.from_content("mockllm", "追記しました"),
        ]
    )
    resumed = InterviewStateAgent.from_checkpoint_file(
        resumed_model.model,
        checkpoint_path,
        max_tool_rounds=4,
    )

    assert len(resumed.history) == 0
    asyncio.run(resumed.process_utterance("担当は営業です"))

    assert restored_state == first_agent.state
    assert [item.id for item in resumed.state.utterances] == ["u1", "u2"]
    assert resumed.checkpoint().next_utterance_number == 3
    assert len(resumed.history) == 1
    assert (
        resumed.state.business_model.process_steps[0].actor.entity_id == "actor:sales"
    )


def test_checkpoint_rejects_public_user_body_that_differs_from_utterance(
    tmp_path: Path,
) -> None:
    agent = _agent([ModelOutput.from_content("mockllm", "確認しました")])
    asyncio.run(agent.process_utterance("申請内容を確認します"))
    checkpoint_path = tmp_path / "mismatch.json"
    agent.save_checkpoint(checkpoint_path)

    payload = load_checkpoint(checkpoint_path).model_dump(mode="json")
    payload["public_messages"][0]["content"] = "別の発言"
    checkpoint_path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )

    with pytest.raises(InterviewAgentError, match="invalid interview checkpoint"):
        load_checkpoint(checkpoint_path)


def test_checkpoint_resume_reaches_executor_for_correction_with_short_answer(
    tmp_path: Path,
) -> None:
    first = "申請内容を確認し、担当は経理です。"
    question = "確認を担当するのは経理ですか？"
    first_agent = _agent(
        [
            ModelOutput.for_tool_call(
                "mockllm",
                "record_process_step",
                {
                    "step_id": "step:review",
                    "activity": {"state": "value", "value": "申請を確認"},
                    "actor": {"id": "actor:accounting", "label": "経理"},
                    "evidence": [_candidate("u1")],
                },
            ),
            ModelOutput.from_content("mockllm", question),
        ]
    )
    asyncio.run(first_agent.process_utterance(first))
    checkpoint_path = tmp_path / "correction.json"
    first_agent.save_checkpoint(checkpoint_path)

    resumed_model = _agent(
        [
            ModelOutput.for_tool_call(
                "mockllm",
                "revise_record",
                {
                    "record_id": "step:review",
                    "field": "actor",
                    "replacement_id": "claim:step:review:actor:sales",
                    "statement": "担当は営業です。",
                    "value": {"id": "actor:sales", "label": "営業"},
                    "correction_note": "短い回答で担当者を訂正した。",
                    "evidence": [_candidate("u2")],
                },
            ),
            ModelOutput.from_content("mockllm", "担当者を訂正しました。"),
        ]
    )
    resumed = InterviewStateAgent.from_checkpoint_file(
        resumed_model.model,
        checkpoint_path,
        max_tool_rounds=4,
    )
    answer = "いいえ、営業です"
    turn = asyncio.run(resumed.process_utterance(answer))

    assert turn.invocations[0].receipt is not None
    assert [item.id for item in resumed.state.business_model.process_steps] == [
        "step:review"
    ]
    old_claim = next(
        item
        for item in resumed.state.claims
        if item.predicate == "actor" and item.status == "rejected"
    )
    current_claim = next(
        item
        for item in resumed.state.claims
        if item.predicate == "actor" and item.status != "rejected"
    )
    assert current_claim.supersedes == old_claim.id
    assert current_claim.evidence[0].quote == answer
    assert (
        resumed.state.business_model.process_steps[0].actor.entity_id == "actor:sales"
    )


def test_assistant_question_is_not_an_evidence_candidate_for_short_answer(
    tmp_path: Path,
) -> None:
    question = "確認を担当するのは経理ですか？"
    first_agent = _agent([ModelOutput.from_content("mockllm", question)])
    asyncio.run(first_agent.process_utterance("申請内容を確認する業務です。"))
    checkpoint_path = tmp_path / "boundary.json"
    first_agent.save_checkpoint(checkpoint_path)
    question_message = first_agent.public_messages[1]

    resumed_model = _agent(
        [
            ModelOutput.for_tool_call(
                "mockllm",
                "record_process_step",
                {
                    "step_id": "step:bad",
                    "activity": {"state": "value", "value": "確認"},
                    "evidence": [
                        {
                            "candidate_id": candidate_id_for_utterance(
                                question_message.id
                            )
                        }
                    ],
                },
            ),
            ModelOutput.for_tool_call(
                "mockllm",
                "record_process_step",
                {
                    "step_id": "step:review",
                    "activity": {"state": "value", "value": "確認"},
                    "evidence": [_candidate("u2")],
                },
            ),
            ModelOutput.from_content("mockllm", "回答を記録しました。"),
        ]
    )
    resumed = InterviewStateAgent.from_checkpoint_file(
        resumed_model.model,
        checkpoint_path,
        max_tool_rounds=4,
    )
    answer = "はい"
    turn = asyncio.run(resumed.process_utterance(answer))

    assert turn.invocations[0].receipt is None
    assert turn.invocations[0].error is not None
    assert "unpublished evidence candidate" in turn.invocations[0].error
    assert turn.invocations[1].receipt is not None
    assert resumed.state.claims[0].evidence[0].quote == answer
    assert question not in [item.text for item in resumed.state.utterances]
    assert resumed.public_messages[2].reply_to == question_message.id


def test_repeated_checkpoint_resume_does_not_duplicate_public_history_or_tools(
    tmp_path: Path,
) -> None:
    first_agent = _agent(
        [
            ModelOutput.for_tool_call(
                "mockllm",
                "record_process_step",
                {
                    "step_id": "step:review",
                    "activity": {"state": "value", "value": "申請を確認"},
                    "evidence": [_candidate("u1")],
                },
            ),
            ModelOutput.from_content("mockllm", "確認を担当するのは経理ですか？"),
        ]
    )
    asyncio.run(first_agent.process_utterance("申請内容を確認する業務です。"))
    first_path = tmp_path / "first.json"
    first_agent.save_checkpoint(first_path)

    resumed_model = _RecordingModel(
        [ModelOutput.from_content("mockllm", "回答を受け取りました。")]
    )
    resumed = InterviewStateAgent.from_checkpoint_file(
        resumed_model,
        first_path,
        max_tool_rounds=4,
    )
    assert resumed.history == ()
    assert resumed_model.inputs == []
    asyncio.run(resumed.process_utterance("はい"))
    second_path = tmp_path / "second.json"
    resumed.save_checkpoint(second_path)

    restored_model = _RecordingModel([])
    restored = InterviewStateAgent.from_checkpoint_file(
        restored_model,
        second_path,
        max_tool_rounds=4,
    )
    third_path = tmp_path / "third.json"
    restored.save_checkpoint(third_path)
    second = load_checkpoint(second_path)
    third = load_checkpoint(third_path)

    assert restored.history == ()
    assert restored_model.inputs == []
    assert second.public_messages == third.public_messages
    assert [message.role for message in third.public_messages] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert [message.content for message in third.public_messages] == [
        "申請内容を確認する業務です。",
        "確認を担当するのは経理ですか？",
        "はい",
        "回答を受け取りました。",
    ]
    assert [message.sequence for message in third.public_messages] == list(
        range(len(third.public_messages))
    )
    assert len({message.id for message in third.public_messages}) == len(
        third.public_messages
    )
    assert len(third.state.claims) == 1
    checkpoint_json = second_path.read_text(encoding="utf-8")
    for private_name in ("tool_calls", "tool_call_id", "assistant_text", "reasoning"):
        assert f'"{private_name}":' not in checkpoint_json


def test_failure_metadata_classifies_provider_errors_without_echoing_credentials() -> (
    None
):
    agent = _agent(
        [ModelOutput(model="mockllm", error="authorization=sk-secret-value")]
    )

    with pytest.raises(InterviewAgentError) as caught:
        asyncio.run(agent.process_utterance("申請を確認します"))

    assert caught.value.kind == "provider_error"
    assert agent.metadata.execution_status == "technical_failure"
    assert agent.metadata.last_failure_kind == "provider_error"
    assert "sk-secret" not in agent.metadata.model_dump_json()
    assert agent.metadata.last_failure_message == "model provider returned an error"


def test_report_preserves_readable_flow_and_completion_sections() -> None:
    agent = _agent([ModelOutput.from_content("mockllm", "記録なし")])
    report = render_interview_report(agent.state, metadata=agent.metadata)

    assert "## Current business flow" in report
    assert "## Evidence and claims" in report
    assert "## Completion" in report
    assert "prompt version" in report


def test_report_shows_question_linked_to_short_answer() -> None:
    question = "確認を担当するのは経理ですか？"
    agent = _agent(
        [
            ModelOutput.from_content("mockllm", question),
            ModelOutput.from_content("mockllm", "はいを確認しました"),
        ]
    )
    asyncio.run(agent.process_utterance("申請内容を確認する業務です。"))
    asyncio.run(agent.process_utterance("はい"))

    report = render_interview_report(
        agent.state,
        metadata=agent.metadata,
        public_messages=agent.public_messages,
    )

    assert "## Public conversation" in report
    assert question in report
    assert "reply_to=`public:assistant:0001`" in report
