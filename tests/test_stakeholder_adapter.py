"""Inspect mock-model integration tests for one stakeholder response."""

# The workspace-level auxiliary resolver may not see the Inspect dev group.
# Project-level ``uv run pyright`` remains the authoritative adapter check.
# pyright: reportMissingImports=false

from __future__ import annotations

import json
from typing import Any

import pytest
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
from inspect_ai.util import json_schema

from business_interview.models import STRUCTURAL_SINK_ID, STRUCTURAL_SOURCE_ID
from business_interview.runtime import create_live_interview_store
from business_interview.stakeholders.knowledge import (
    KnowledgeConceptRef,
    StakeholderEdge,
    StakeholderKnowledge,
    StakeholderKnowledgeConcept,
    StakeholderKnowledgeGraph,
    StakeholderNode,
)
from business_interview.stakeholders.response import (
    SemanticResponsePlan,
    StakeholderResponse,
)
from business_interview_bench.inspect_adapter.stakeholder import (
    StakeholderResponseError,
    invoke_stakeholder_response,
    invoke_stakeholder_response_with_plan,
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


def test_nonempty_what_to_annotated_how_is_ingested_in_semantic_ledger(
    tmp_path,
) -> None:
    captured: list[tuple[Any, Any]] = []
    stakeholder_model = get_model(
        "mockllm/stakeholder",
        custom_outputs=[_plan_output(), _response_output()],
    )

    @solver
    def mock_stakeholder_solver() -> Solver:
        async def solve(state: TaskState, generate: Any) -> TaskState:
            del generate
            runtime = create_live_interview_store("response")
            runtime = runtime.record_candidate_turn()
            runtime = runtime.record_candidate_question("What do you do?")
            turn = await invoke_stakeholder_response_with_plan(
                [ChatMessageUser(content="What do you do?")],
                _knowledge(),
            )
            runtime = runtime.ingest_stakeholder_response(
                _knowledge(), turn.plan, turn.response
            )
            captured.append((turn, runtime))
            state.completed = True
            return state

        return solve

    logs = inspect_eval(
        Task(
            dataset=[Sample(id="response", input="What do you do?")],
            solver=mock_stakeholder_solver(),
            model="none",
        ),
        model="none",
        model_roles={"stakeholder": stakeholder_model},
        score=False,
        display="none",
        log_dir=str(tmp_path),
    )

    assert len(logs) == 1
    assert logs[0].status == "success"
    assert len(captured) == 1
    turn, runtime = captured[0]
    assert len(turn.plan.items) == 1
    assert len(turn.response.annotations) == 1
    annotation = turn.response.annotations[0]
    planned = turn.plan.items[0]
    assert (annotation.semantic_id, annotation.mode) == (
        planned.semantic_id,
        planned.mode,
    )
    assert annotation.quote in turn.response.message
    entry = runtime.semantic_ledger.entries[-1]
    assert entry.plan == turn.plan
    assert entry.annotations == turn.response.annotations
    assert runtime.observations[-1].text == turn.response.message
    assert runtime.public_message_ledger[-1].content == turn.response.message
    assert "semantic_id" not in runtime.public_message_ledger[-1].content
    assert "skn_001" not in runtime.public_message_ledger[-1].content


def test_native_response_schema_is_used_for_both_phases(tmp_path) -> None:
    log, captured, errors = _run_mock_response(
        tmp_path,
        [_plan_output(), _response_output()],
    )

    assert log.status == "success"
    assert captured and not errors
    events = _model_events(log)
    schemas = [event.config.response_schema for event in events]
    assert [schema.name for schema in schemas] == [
        "semantic_response_plan",
        "stakeholder_response",
    ]
    assert all(schema.strict is False for schema in schemas)
    assert all(schema.json_schema.type == "object" for schema in schemas)
    assert all(schema.json_schema.additionalProperties is False for schema in schemas)
    assert schemas[0].json_schema == json_schema(SemanticResponsePlan)
    assert schemas[1].json_schema == json_schema(StakeholderResponse)
    assert all(
        "$ref" not in json.dumps(schema.json_schema.model_dump(mode="json"))
        for schema in schemas
    )


def test_common_provider_json_wrappers_are_extracted_without_semantic_repair(
    tmp_path,
) -> None:
    plan = _plan_output()
    plan.completion = (
        "prefix ```json\n"
        '{"items": [{"semantic_id": "node:skn_001:activity", "mode": "value"}]}\n'
        "``` suffix"
    )
    response = _response_output()
    response.completion = (
        "Here is the response: "
        '{"message": "I review requests.", "annotations": ['
        '{"semantic_id": "node:skn_001:activity", "mode": "value", '
        '"quote": "review requests", "occurrence": 0}], '
        '"alignments": [], "terminology": []} trailing text'
    )
    log, captured, errors = _run_mock_response(tmp_path, [plan, response])

    assert log.status == "success"
    assert not errors
    assert captured[0].message == "I review requests."
    assert len(_model_events(log)) == 2


def test_structural_retry_diagnostic_is_distinct_and_safe(tmp_path) -> None:
    invalid_plan = ModelOutput.from_content("mockllm", "not json")
    log, captured, errors = _run_mock_response(
        tmp_path,
        [invalid_plan, _plan_output(), _response_output()],
    )

    assert log.status == "success"
    assert captured and not errors
    retry_input = _model_events(log)[1].input[-1].text
    assert "Previous output rejected: [structural]" in retry_input
    assert "not json" not in retry_input


def test_semantic_retry_diagnostic_is_distinct_and_safe(tmp_path) -> None:
    invalid_plan = ModelOutput.from_content(
        "mockllm",
        '{"items": [{"semantic_id": "node:missing", "mode": "exists"}]}',
    )
    log, captured, errors = _run_mock_response(
        tmp_path,
        [invalid_plan, _plan_output(), _response_output()],
    )

    assert log.status == "success"
    assert captured and not errors
    retry_input = _model_events(log)[1].input[-1].text
    assert "Previous output rejected: [semantic]" in retry_input
    assert "node:missing" not in retry_input


@pytest.mark.parametrize(
    ("invalid_plan", "expected_code", "expected_guidance"),
    [
        (
            '{"items": [{"semantic_id": "node:missing", "mode": "exists"}]}',
            "unresolvable_address",
            "not present in the supplied stakeholder knowledge",
        ),
        (
            '{"items": [{"semantic_id": "node:skn_001", "mode": "value"}]}',
            "mode_mismatch",
            "wrong mode for a semantic item",
        ),
    ],
)
def test_what_failure_categories_are_typed_and_safe(
    tmp_path,
    invalid_plan: str,
    expected_code: str,
    expected_guidance: str,
) -> None:
    log, captured, errors = _run_mock_response(
        tmp_path,
        [ModelOutput.from_content("mockllm", invalid_plan) for _ in range(3)],
        catch_error=True,
    )

    assert log.status == "success"
    assert not captured
    assert len(errors) == 1
    error = errors[0]
    assert error.diagnostics is not None
    assert error.diagnostics.what_semantic_rejections == 3
    retry_input = _model_events(log)[1].input[-1].text
    assert expected_guidance in retry_input
    assert "node:missing" not in retry_input
    if expected_code == "unresolvable_address":
        assert error.diagnostics.what_unresolvable_address_count == 3
        assert error.diagnostics.what_mode_mismatch_count == 0
    else:
        assert error.diagnostics.what_unresolvable_address_count == 0
        assert error.diagnostics.what_mode_mismatch_count == 3
    assert error.diagnostics.what_realization_semantic_mismatch_count == 0


def test_output_exhaustion_is_retried_and_classified_separately(tmp_path) -> None:
    exhausted = ModelOutput.from_content("mockllm", "", stop_reason="max_tokens")
    log, captured, errors = _run_mock_response(
        tmp_path,
        [exhausted, _plan_output(), _response_output()],
    )

    assert log.status == "success"
    assert captured and not errors
    retry_input = _model_events(log)[1].input[-1].text
    assert "Previous output rejected: [output_exhaustion]" in retry_input
    assert "token limit" in retry_input


def test_output_exhaustion_retry_bound_is_not_a_semantic_failure(tmp_path) -> None:
    exhausted = ModelOutput.from_content("mockllm", "", stop_reason="max_tokens")
    log, captured, errors = _run_mock_response(
        tmp_path,
        [exhausted, exhausted, exhausted],
        catch_error=True,
    )

    assert log.status == "success"
    assert not captured
    assert len(errors) == 1
    assert errors[0].failure_kind == "output_exhaustion"
    assert errors[0].failure_reason == "stakeholder_what_output_exhaustion_exhausted"
    assert errors[0].diagnostics is not None
    assert errors[0].diagnostics.output_exhaustion_count == 3
    assert errors[0].diagnostics.what_structural_rejections == 0
    assert errors[0].diagnostics.what_semantic_rejections == 0
    assert errors[0].diagnostics.retry_count == 2


def test_provider_generation_error_is_not_retried_as_semantic_output(tmp_path) -> None:
    provider_error = ModelOutput.from_content("mockllm", "", error="provider failure")
    log, captured, errors = _run_mock_response(
        tmp_path,
        [provider_error],
        catch_error=True,
    )

    assert log.status == "success"
    assert not captured
    assert len(errors) == 1
    assert errors[0].failure_kind == "provider"
    assert errors[0].failure_reason == ("stakeholder_what_provider_generation_failure")
    assert errors[0].diagnostics is not None
    assert errors[0].diagnostics.provider_error_count == 1
    assert errors[0].diagnostics.retry_count == 0
    assert len(_model_events(log)) == 1


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


def test_retry_exhaustion_is_an_explicit_structural_error(tmp_path) -> None:
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
    assert errors[0].failure_kind == "structural"
    assert errors[0].failure_reason == "stakeholder_what_structural_exhausted"
    assert errors[0].retry_exhausted is True
    assert errors[0].diagnostics is not None
    assert errors[0].diagnostics.what_structural_rejections == 3
    assert errors[0].diagnostics.retry_count == 2
    assert len(_model_events(log)) == 3
