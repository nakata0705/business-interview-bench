"""MockLLM coverage for the real-model InterviewState adapter boundary."""

# The workspace resolver may not index the Inspect dev group or new siblings;
# project-level ``uv run pyright`` is authoritative for these tests.
# pyright: reportMissingImports=false

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from inspect_ai.model import ModelOutput, get_model

from business_interview_bench.interview_agent import (
    InterviewStateAgent,
    load_checkpoint,
)


def _citation(utterance_id: str, text: str) -> dict[str, object]:
    return {
        "utterance_id": utterance_id,
        "start": 0,
        "end": len(text),
        "quote": text,
        "semantic_support": "supports",
    }


def _agent(outputs: list[ModelOutput]) -> InterviewStateAgent:
    model = get_model(
        "mockllm/interview-state-agent-test",
        custom_outputs=outputs,
    )
    return InterviewStateAgent(model, max_tool_rounds=4)


def test_provider_tool_definitions_inline_pydantic_references() -> None:
    agent = _agent([ModelOutput.from_content("mockllm", "ack")])

    for definition in agent.tools:
        rendered = json.dumps(
            definition.parameters.model_dump(mode="json"),
            ensure_ascii=False,
        )
        assert "$defs" not in rendered
        assert "$ref" not in rendered
        assert definition.parameters.additionalProperties is False


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
                    "evidence": [_citation("u1", text)],
                },
            ),
            ModelOutput.from_content("mockllm", "記録しました"),
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
    assert "Ready-to-use exact evidence candidate" in agent.messages[1].text


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
                    "evidence": [_citation("u1", first)],
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
                    "evidence": [_citation("u2", second)],
                },
            ),
            ModelOutput.from_content("mockllm", "担当者を追記しました"),
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
    assert actor_claim.evidence[0].utterance_id == "u2"


def test_checkpoint_round_trip_resumes_with_next_public_utterance(
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
                    "evidence": [_citation("u1", first)],
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
    restored_state = checkpoint.state
    resumed = InterviewStateAgent.from_checkpoint_file(
        _agent(
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
                        "evidence": [_citation("u2", "担当は営業です")],
                    },
                ),
                ModelOutput.from_content("mockllm", "追記しました"),
            ]
        ).model,
        checkpoint_path,
        max_tool_rounds=4,
    )

    asyncio.run(resumed.process_utterance("担当は営業です"))

    assert restored_state == first_agent.state
    assert [item.id for item in resumed.state.utterances] == ["u1", "u2"]
    assert resumed.checkpoint().next_utterance_number == 3
    assert (
        resumed.state.business_model.process_steps[0].actor.entity_id == "actor:sales"
    )
