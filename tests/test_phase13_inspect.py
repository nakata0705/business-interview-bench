"""Actual Inspect-path MockLLM integration for Phase 13."""

# The workspace-level auxiliary resolver may not see freshly added siblings;
# project-level ``uv run pyright`` is authoritative for this package.
# pyright: reportMissingImports=false

from __future__ import annotations

from typing import Any, cast

import pytest
from inspect_ai import eval as inspect_eval
from inspect_ai.log import read_eval_log
from inspect_ai.model import ModelName, ModelOutput, get_model
from inspect_ai.solver import TaskState

from business_interview.scenarios import get_scenario
from business_interview.stakeholders import (
    StakeholderKnowledge,
    StakeholderProfile,
    knowledge_coverage_view,
    project_knowledge,
)
from business_interview_bench.inspect_adapter.live_store import (
    BusinessInterviewLiveStore,
    persist_evaluation_inputs,
)
from business_interview_bench.inspect_adapter.multiturn import (
    MultiTurnInterviewError,
    phase13_interview_task,
    phase13_smoke_interview_task,
)


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
        ModelOutput.for_tool_call("mockllm", "get_agent_graph", {}),
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
    *,
    scenario_id: str = "lab_sample_flow",
    max_candidate_steps_per_turn: int = 8,
    stakeholder_outputs: list[ModelOutput] | None = None,
) -> Any:
    task = phase13_smoke_interview_task(
        scenario_id=scenario_id,
        max_turns=max_turns,
        max_candidate_steps_per_turn=max_candidate_steps_per_turn,
    )
    logs = inspect_eval(
        task,
        model=get_model("mockllm/candidate", custom_outputs=candidate_outputs),
        model_roles={
            "stakeholder": get_model(
                "mockllm/stakeholder",
                custom_outputs=(
                    stakeholder_outputs
                    if stakeholder_outputs is not None
                    else _stakeholder_outputs(stakeholder_messages)
                ),
            )
        },
        display="none",
        log_dir=str(tmp_path),
    )
    assert len(logs) == 1
    assert logs[0].location
    return read_eval_log(logs[0].location, resolve_attachments="full")


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
        "get_agent_graph",
        "set_node_property",
        "complete_interview",
    ]
    tool_events = [
        event for event in log.samples[0].events if type(event).__name__ == "ToolEvent"
    ]
    graph_result = next(
        event.result for event in tool_events if event.function == "get_agent_graph"
    )
    assert '"nodes"' in graph_result
    for event in tool_events:
        if event.function != "get_agent_graph":
            assert '"nodes"' not in event.result
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
    assert runtime_store.stakeholder_knowledge
    assert runtime_store.stakeholder_profile == {}
    assert runtime_store.stakeholder_seed == 0


def test_missing_stakeholder_setup_is_an_explicit_error() -> None:
    with pytest.raises(MultiTurnInterviewError, match="stakeholder setup is required"):
        phase13_interview_task()


def test_profile_seed_and_exact_knowledge_round_trip_in_private_store() -> None:
    truth = get_scenario("lab_sample_flow").truth
    business_nodes = tuple(
        node_id for node_id, node in truth.nodes.items() if not node.is_structural
    )
    business_edges = tuple(
        edge_id for edge_id, edge in truth.edges.items() if not edge.is_structural
    )
    profile = StakeholderProfile(
        stakeholder_id="phase13-test-profile",
        name="Phase 13 test profile",
        role="lab technician",
        visible_node_ids=business_nodes,
        visible_edge_ids=business_edges,
        visible_node_attributes={node_id: ("activity",) for node_id in business_nodes},
        visible_edge_attributes={edge_id: ("condition",) for edge_id in business_edges},
    )
    knowledge = project_knowledge(truth, profile, seed=17)
    coverage = knowledge_coverage_view(truth, knowledge)
    store = BusinessInterviewLiveStore()
    persist_evaluation_inputs(
        store,
        truth,
        coverage,
        stakeholder_profile=profile,
        stakeholder_seed=17,
        stakeholder_knowledge=knowledge,
    )
    restored = BusinessInterviewLiveStore.model_validate(store.model_dump())
    assert StakeholderProfile.model_validate(restored.stakeholder_profile) == profile
    assert restored.stakeholder_seed == 17
    restored_knowledge = StakeholderKnowledge.model_validate(
        restored.stakeholder_knowledge
    )
    assert restored_knowledge == knowledge
    assert restored_knowledge.model_dump(mode="json") == restored.stakeholder_knowledge


def test_candidate_tool_steps_stop_without_a_stakeholder_call(tmp_path) -> None:
    candidate_outputs = [
        ModelOutput.for_tool_call("mockllm", "get_observations", {}) for _ in range(5)
    ]
    log = _run(
        tmp_path,
        candidate_outputs,
        (),
        max_turns=4,
        max_candidate_steps_per_turn=2,
    )
    assert log.status == "success"
    runtime = _sample_store(log).live_state
    assert runtime["protocol_state"] == {
        "status": "incomplete",
        "completion_reason": None,
        "failure_reason": "candidate_step_limit_exhausted",
        "terminal_turn": 1,
    }
    assert runtime["candidate_turns"] == 1
    assert runtime["candidate_steps"] == 2
    assert runtime["stakeholder_turns"] == 0
    events = _model_events(log)
    assert len([event for event in events if event.role != "stakeholder"]) == 2
    assert not any(event.role == "stakeholder" for event in events)


@pytest.mark.parametrize(
    ("scenario_id", "prompt_fragments"),
    [
        (
            "lab_sample_flow",
            (
                "You are a lab technician",
                "You have been asked to take part",
                "Answer the interviewer's questions",
            ),
        ),
        (
            "quotation_workflow_1_ja",
            (
                "あなたは数年間この会社で働いている営業担当者です",
                "チームで見積書がどのように作成されているか",
                "インタビュアーの質問に、ステークホルダーとして",
                "会話全体は日本語で行ってください",
            ),
        ),
    ],
)
def test_scenario_prompt_is_in_both_stakeholder_calls(
    tmp_path,
    scenario_id: str,
    prompt_fragments: tuple[str, ...],
) -> None:
    log = _run(
        tmp_path,
        [
            ModelOutput.from_content("mockllm", "What do you do?"),
            ModelOutput.for_tool_call(
                "mockllm", "complete_interview", {"reason": "done"}
            ),
        ],
        ("Answer.",),
        max_turns=2,
        scenario_id=scenario_id,
    )
    assert log.status == "success"
    stakeholder_events = [
        event for event in _model_events(log) if event.role == "stakeholder"
    ]
    assert len(stakeholder_events) == 2
    for event in stakeholder_events:
        system_context = event.input[0].text
        assert all(fragment in system_context for fragment in prompt_fragments)


def test_mutation_tool_error_preserves_concrete_reason(tmp_path) -> None:
    log = _run(
        tmp_path,
        [
            ModelOutput.for_tool_call("mockllm", "add_node", {"node_id": "n1"}),
            ModelOutput.for_tool_call("mockllm", "add_node", {"node_id": "n1"}),
            ModelOutput.from_content("mockllm", "Question?"),
            ModelOutput.for_tool_call(
                "mockllm", "complete_interview", {"reason": "done"}
            ),
        ],
        ("Answer.",),
        max_turns=2,
    )
    assert log.status == "success"
    errors = [
        event.error
        for event in log.samples[0].events
        if type(event).__name__ == "ToolEvent" and event.error is not None
    ]
    assert len(errors) == 1
    assert "node already exists" in errors[0].message
    assert "AgentGraph mutation failed" not in errors[0].message


def test_phase13_terminology_keeps_both_public_provenance_spans(tmp_path) -> None:
    stakeholder_outputs = [
        ModelOutput.from_content("mockllm", '{"items": []}'),
        ModelOutput.from_content(
            "mockllm",
            '{"message": "Yes.", "annotations": [], "alignments": [], '
            '"terminology": [{"semantic_id": "skc_002", '
            '"proposed_term": "accession step", "proposal_turn": 2, '
            '"proposal_quote": "Can we call this an accession step?", '
            '"proposal_occurrence": 0, "quote": "Yes.", "occurrence": 0}]}',
        ),
    ]
    log = _run(
        tmp_path,
        [
            ModelOutput.from_content("mockllm", "Can we call this an accession step?"),
            ModelOutput.for_tool_call(
                "mockllm", "complete_interview", {"reason": "done"}
            ),
        ],
        (),
        max_turns=2,
        stakeholder_outputs=stakeholder_outputs,
    )
    assert log.status == "success"
    runtime_store = _sample_store(log)
    terminology = runtime_store.semantic_ledger.terminology
    assert len(terminology) == 1
    event = terminology[0]
    assert event.proposal_turn == 2
    assert event.proposal_quote == "Can we call this an accession step?"
    assert event.quote == "Yes."
    assert runtime_store.stakeholder_knowledge


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
