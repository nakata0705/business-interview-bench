"""Inspect mock-model integration tests for one stakeholder response."""

# The workspace-level auxiliary resolver may not see the Inspect dev group.
# Project-level ``uv run pyright`` remains the authoritative adapter check.
# pyright: reportMissingImports=false

from __future__ import annotations

from typing import Any

from inspect_ai import Task
from inspect_ai import eval as inspect_eval
from inspect_ai.dataset import Sample
from inspect_ai.log import read_eval_log
from inspect_ai.model import (
    ChatMessageUser,
    ModelOutput,
    get_model,
)
from inspect_ai.solver import Solver, TaskState, solver

from business_interview.models import STRUCTURAL_SINK_ID, STRUCTURAL_SOURCE_ID
from business_interview.stakeholders.knowledge import (
    KnowledgeConceptRef,
    StakeholderEdge,
    StakeholderKnowledge,
    StakeholderKnowledgeConcept,
    StakeholderKnowledgeGraph,
    StakeholderNode,
)
from business_interview_bench.inspect_adapter.stakeholder import (
    StakeholderResponseError,
    invoke_stakeholder_response,
)

_SOURCE_EDGE = "__tau2_structural_boundary__source_001"
_SINK_EDGE = "__tau2_structural_boundary__sink_001"


def _knowledge() -> StakeholderKnowledge:
    concepts = {
        "skc_activity": StakeholderKnowledgeConcept(
            id="skc_activity",
            truth_concept_id="truth_activity",
            kind="activity",
            description="review requests",
            terms=("review request",),
        )
    }
    nodes = {
        STRUCTURAL_SOURCE_ID: StakeholderNode(
            id=STRUCTURAL_SOURCE_ID,
            structural=True,
            structural_role="source",
            protected=True,
        ),
        "skn_001": StakeholderNode(
            id="skn_001",
            activity=KnowledgeConceptRef(concept_id="skc_activity"),
        ),
        "skn_002": StakeholderNode(
            id="skn_002",
            activity=KnowledgeConceptRef(concept_id="skc_activity"),
        ),
        STRUCTURAL_SINK_ID: StakeholderNode(
            id=STRUCTURAL_SINK_ID,
            structural=True,
            structural_role="sink",
            protected=True,
        ),
    }
    edges = {
        _SOURCE_EDGE: StakeholderEdge(
            id=_SOURCE_EDGE,
            from_node=STRUCTURAL_SOURCE_ID,
            to_node="skn_001",
            edge_kind="structural_boundary",
            structural_only=True,
            protected=True,
        ),
        "ske_001": StakeholderEdge(
            id="ske_001",
            from_node="skn_001",
            to_node="skn_002",
        ),
        _SINK_EDGE: StakeholderEdge(
            id=_SINK_EDGE,
            from_node="skn_002",
            to_node=STRUCTURAL_SINK_ID,
            edge_kind="structural_boundary",
            structural_only=True,
            protected=True,
        ),
    }
    return StakeholderKnowledge(
        graph=StakeholderKnowledgeGraph(
            nodes=nodes,
            edges=edges,
            concepts=concepts,
        )
    )


def _plan_output() -> ModelOutput:
    return ModelOutput.from_content(
        model="mockllm",
        content=(
            '{"items": [{"semantic_id": "node:skn_001:activity", "mode": "value"}]}'
        ),
    )


def _response_output() -> ModelOutput:
    return ModelOutput.from_content(
        model="mockllm",
        content=(
            '{"message": "I review requests.", "annotations": ['
            '{"semantic_id": "node:skn_001:activity", "mode": "value", '
            '"quote": "review requests", "occurrence": 0}], '
            '"alignments": [], "terminology": []}'
        ),
    )


def _run_mock_response(
    tmp_path, outputs: list[ModelOutput], *, catch_error: bool = False
) -> tuple[Any, list[Any], list[StakeholderResponseError]]:
    captured: list[Any] = []
    errors: list[StakeholderResponseError] = []
    stakeholder_model = get_model(
        "mockllm/stakeholder",
        custom_outputs=outputs,
    )

    @solver
    def mock_stakeholder_solver() -> Solver:
        async def solve(state: TaskState, generate: Any) -> TaskState:
            del generate
            try:
                captured.append(
                    await invoke_stakeholder_response(
                        [ChatMessageUser(content="What do you do?")],
                        _knowledge(),
                    )
                )
            except StakeholderResponseError as exc:
                if not catch_error:
                    raise
                errors.append(exc)
            state.completed = True
            return state

        return solve

    task = Task(
        dataset=[Sample(id="response", input="What do you do?")],
        solver=mock_stakeholder_solver(),
        model="none",
    )
    logs = inspect_eval(
        task,
        model="none",
        model_roles={"stakeholder": stakeholder_model},
        score=False,
        display="none",
        log_dir=str(tmp_path),
    )
    assert len(logs) == 1
    return logs[0], captured, errors


def _model_events(log: Any) -> list[Any]:
    if log.location:
        log = read_eval_log(log.location, resolve_attachments="core")
    assert log.samples and len(log.samples) == 1
    return [
        event for event in log.samples[0].events if type(event).__name__ == "ModelEvent"
    ]


def test_mock_stakeholder_role_uses_exactly_two_successful_calls(tmp_path) -> None:
    log, captured, errors = _run_mock_response(
        tmp_path,
        [_plan_output(), _response_output()],
    )

    assert log.status == "success"
    assert not errors
    assert len(captured) == 1
    assert captured[0].message == "I review requests."
    events = _model_events(log)
    assert len(events) == 2
    assert all(event.role == "stakeholder" for event in events)
    assert all(event.error is None for event in events)


def test_invalid_plan_retries_before_realization(tmp_path) -> None:
    invalid_plan = ModelOutput.from_content(
        model="mockllm",
        content='{"items": [{"semantic_id": "node:missing", "mode": "exists"}]}',
    )
    log, captured, errors = _run_mock_response(
        tmp_path,
        [invalid_plan, _plan_output(), _response_output()],
    )

    assert log.status == "success"
    assert not errors
    assert len(captured) == 1
    events = _model_events(log)
    assert len(events) == 3
    assert "Previous output rejected" in events[1].input[-1].text


def test_invalid_realization_retries_with_the_same_plan(tmp_path) -> None:
    invalid_response = ModelOutput.from_content(
        model="mockllm",
        content=(
            '{"message": "I review requests.", "annotations": [], '
            '"alignments": [], "terminology": []}'
        ),
    )
    log, captured, errors = _run_mock_response(
        tmp_path,
        [_plan_output(), invalid_response, _response_output()],
    )

    assert log.status == "success"
    assert not errors
    assert len(captured) == 1
    events = _model_events(log)
    assert len(events) == 3
    assert "Previous output rejected" in events[2].input[-1].text


def test_retry_exhaustion_is_an_explicit_error(tmp_path) -> None:
    invalid_plan = ModelOutput.from_content(model="mockllm", content="not json")
    log, captured, errors = _run_mock_response(
        tmp_path,
        [invalid_plan, invalid_plan, invalid_plan],
        catch_error=True,
    )

    assert log.status == "success"
    assert not captured
    assert len(errors) == 1
    assert "plan rejected after 3 attempts" in str(errors[0])
    assert len(_model_events(log)) == 3
