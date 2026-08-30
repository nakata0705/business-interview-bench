"""Actual Inspect-path MockLLM integration for Phase 13."""

# The workspace-level auxiliary resolver may not see freshly added siblings;
# project-level ``uv run pyright`` is authoritative for this package.
# pyright: reportMissingImports=false

from __future__ import annotations

from typing import Any, cast

from inspect_ai import eval as inspect_eval
from inspect_ai.log import read_eval_log
from inspect_ai.model import ModelName, ModelOutput, get_model
from inspect_ai.solver import TaskState

from business_interview_bench.inspect_adapter.live_store import (
    BusinessInterviewLiveStore,
)
from business_interview_bench.inspect_adapter.multiturn import phase13_interview_task


def _candidate_turns() -> list[ModelOutput]:
    return [
        ModelOutput.for_tool_call(
            "mockllm",
            "define_concept",
            {
                "concept_id": "c1",
                "kind": "activity",
                "display_label": "condition sample",
            },
        ),
        ModelOutput.for_tool_call(
            "mockllm",
            "add_node",
            {"node_id": "n1"},
        ),
        ModelOutput.from_content("mockllm", "What do you do first?"),
        ModelOutput.for_tool_call(
            "mockllm",
            "set_node_property",
            {
                "node_id": "n1",
                "property_name": "activity",
                "value": "c1",
            },
        ),
        ModelOutput.from_content("mockllm", "And what happens next?"),
        ModelOutput.for_tool_call(
            "mockllm",
            "complete_interview",
            {"reason": "the required questions are covered"},
        ),
    ]


def _stakeholder_outputs(messages: tuple[str, ...]) -> list[ModelOutput]:
    outputs: list[ModelOutput] = []
    for message in messages:
        outputs.extend(
            [
                ModelOutput.from_content("mockllm", '{"items": []}'),
                ModelOutput.from_content(
                    "mockllm",
                    '{"message": "'
                    + message
                    + '", "annotations": [], "alignments": [], "terminology": []}',
                ),
            ]
        )
    return outputs


def _run(
    tmp_path,
    candidate_outputs: list[ModelOutput],
    stakeholder_messages: tuple[str, ...],
    max_turns: int,
) -> Any:
    task = phase13_interview_task(max_turns=max_turns)
    logs = inspect_eval(
        task,
        model=get_model("mockllm/candidate", custom_outputs=candidate_outputs),
        model_roles={
            "stakeholder": get_model(
                "mockllm/stakeholder",
                custom_outputs=_stakeholder_outputs(stakeholder_messages),
            )
        },
        display="none",
        log_dir=str(tmp_path),
    )
    assert len(logs) == 1
    assert logs[0].location
    return read_eval_log(logs[0].location)


def _sample_store(log: Any) -> BusinessInterviewLiveStore:
    assert log.samples and len(log.samples) == 1
    sample = log.samples[0]
    state = TaskState(
        model=cast(ModelName, "none"),
        sample_id=sample.id,
        epoch=sample.epoch,
        input=sample.input,
        messages=sample.messages,
        target=sample.target,
        store=sample.store,
    )
    return state.store_as(BusinessInterviewLiveStore)


def _model_events(log: Any) -> list[Any]:
    assert log.samples and len(log.samples) == 1
    return [
        event for event in log.samples[0].events if type(event).__name__ == "ModelEvent"
    ]


def test_multiturn_mockllm_tools_observations_and_primary_score(tmp_path) -> None:
    log = _run(
        tmp_path,
        _candidate_turns(),
        ("I receive the sample.", "I condition it."),
        max_turns=4,
    )
    assert log.status == "success"
    runtime_store = _sample_store(log)
    runtime = runtime_store.live_state
    assert runtime["protocol_state"]["status"] == "completed"
    assert runtime["protocol_state"]["completion_reason"] == (
        "the required questions are covered"
    )
    assert len(runtime["observations"]) == 3  # one catalog initial user message + two
    assert [item["text"] for item in runtime["observations"][-2:]] == [
        "I receive the sample.",
        "I condition it.",
    ]
    assert len(runtime["semantic_ledger"]["entries"]) == 3
    assert runtime["candidate_turns"] == 3
    assert runtime["stakeholder_turns"] == 2
    assert runtime["question_count"] == 2

    events = _model_events(log)
    stakeholder_events = [event for event in events if event.role == "stakeholder"]
    assert len(stakeholder_events) == 4  # WHAT/HOW, once per public question
    assert all(event.error is None for event in stakeholder_events)
    tool_functions = [
        event.function
        for event in log.samples[0].events
        if type(event).__name__ == "ToolEvent"
    ]
    assert tool_functions == [
        "define_concept",
        "add_node",
        "set_node_property",
        "complete_interview",
    ]
    completion_index = next(
        index
        for index, event in enumerate(events)
        if "complete_interview" in event.output.completion
    )
    assert all(
        index < completion_index or event.role != "stakeholder"
        for index, event in enumerate(events)
    )

    # Candidate messages contain public text and graph tool results only.  The
    # sidecar fields are persisted in Store state, never copied into a message.
    candidate_inputs = [
        message.text
        for event in events
        if event.role != "stakeholder"
        for message in event.input
    ]
    joined = "\n".join(candidate_inputs)
    assert '"annotations": []' not in joined
    assert '"alignments": []' not in joined
    assert '"terminology": []' not in joined
    assert "skn_" not in joined
    assert "ske_" not in joined
    assert "skc_" not in joined
    assert "truth_activity" not in joined
    assert "truth_node" not in joined

    score = log.samples[0].scores["phase13_primary_scorer"]
    assert len(score.value) == 41
    assert score.value["protocol_completed"] is True


def test_max_turn_exhaustion_is_explicit_incomplete_state(tmp_path) -> None:
    candidate_outputs = [
        ModelOutput.from_content("mockllm", "First question?"),
        ModelOutput.from_content("mockllm", "Second question?"),
    ]
    log = _run(
        tmp_path,
        candidate_outputs,
        ("First answer.", "Second answer."),
        max_turns=2,
    )
    assert log.status == "success"
    runtime = _sample_store(log).live_state
    assert runtime["protocol_state"]["status"] == "incomplete"
    assert runtime["protocol_state"]["failure_reason"] == "max_turns_exhausted"
    assert runtime["candidate_turns"] == 2
    assert runtime["stakeholder_turns"] == 2
    stakeholder_events = [
        event for event in _model_events(log) if event.role == "stakeholder"
    ]
    assert len(stakeholder_events) == 4
    assert (
        log.samples[0].scores["phase13_primary_scorer"].value["protocol_completed"]
        is False
    )
