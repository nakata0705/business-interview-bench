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


def test_provider_tool_definitions_use_candidate_evidence_and_inline_refs() -> None:
    agent = _agent([ModelOutput.from_content("mockllm", "ack")])

    for definition in agent.tools:
        rendered = json.dumps(
            definition.parameters.model_dump(mode="json"),
            ensure_ascii=False,
        )
        assert "$defs" not in rendered
        assert "$ref" not in rendered
        assert definition.parameters.additionalProperties is False

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
    assert agent.metadata.execution_status == "technical_failure"


def test_checkpoint_round_trip_excludes_conversation_and_resumes_without_replaying(
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
    assert checkpoint.next_utterance_number == 2
    assert checkpoint.metadata.prompt_version
    assert "messages" not in checkpoint.model_dump(mode="json")
    assert "turns" not in checkpoint.model_dump(mode="json")
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
