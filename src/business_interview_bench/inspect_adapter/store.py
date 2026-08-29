"""Inspect Store schema for the private seed 9004 replay payload."""

# The workspace-level auxiliary resolver may not see the Inspect dev group.
# Project-level ``uv run pyright`` remains the authoritative adapter check.
# pyright: reportMissingImports=false

from __future__ import annotations

from dataclasses import fields
from typing import Any

from inspect_ai.util import StoreModel
from pydantic import Field

from business_interview.evaluation import KnowledgeCoverageView, PrimaryEvaluation
from business_interview.models import (
    AgentGraph,
    BusinessProcessGraph,
    InterviewEvaluationContext,
    validate_canonical_graph,
)
from business_interview.replay_data import load_seed9004_payload


class BusinessInterviewReplayStore(StoreModel):
    """JSON-compatible, sample-scoped inputs needed by the primary scorer.

    Domain models intentionally do not live in the Inspect store. The solver
    writes canonical JSON-compatible dictionaries and the scorer validates
    them back into the standalone domain models before evaluation.
    """

    replay_case_id: str = Field(default="")
    scenario_id: str = Field(default="")
    source_repository: str = Field(default="")
    source_branch: str = Field(default="")
    source_commit_sha: str = Field(default="")
    provenance: dict[str, Any] = Field(default_factory=dict)
    agent: dict[str, Any] = Field(default_factory=dict)
    truth: dict[str, Any] = Field(default_factory=dict)
    evaluation_context: dict[str, Any] = Field(default_factory=dict)
    knowledge_coverage: dict[str, Any] = Field(default_factory=dict)
    expected: dict[str, Any] = Field(default_factory=dict)
    stakeholder_knowledge: dict[str, Any] | None = None


def primary_evaluation_field_names() -> tuple[str, ...]:
    """Return the core result field names without duplicating their schema."""
    return tuple(field.name for field in fields(PrimaryEvaluation))


def _expected_fields(expected: dict[str, Any]) -> dict[str, Any]:
    oracle = expected.get("oracle")
    if not isinstance(oracle, dict):
        raise ValueError("seed 9004 expected payload has no oracle object")
    values = oracle.get("fields")
    if not isinstance(values, dict):
        raise ValueError("seed 9004 expected payload has no oracle fields")
    field_names = primary_evaluation_field_names()
    if len(values) != len(field_names) or set(values) != set(field_names):
        raise ValueError(
            "seed 9004 expected fields do not match PrimaryEvaluation: "
            f"expected {len(field_names)} fields {field_names!r}, "
            f"got {len(values)} fields {tuple(values)!r}"
        )
    return values


def load_seed9004_store_payload() -> dict[str, Any]:
    """Validate the packaged asset and return JSON-only values for Store."""
    agent = AgentGraph.model_validate(load_seed9004_payload("agent.json"))
    truth = BusinessProcessGraph.model_validate(load_seed9004_payload("truth.json"))
    validate_canonical_graph(truth)
    context = InterviewEvaluationContext.model_validate(
        load_seed9004_payload("evaluation_context.json")
    )
    knowledge_coverage = KnowledgeCoverageView.model_validate(
        load_seed9004_payload("knowledge_coverage.json")
    )
    expected = load_seed9004_payload("expected.json")
    _expected_fields(expected)
    provenance = load_seed9004_payload("provenance.json")
    source = provenance.get("source")
    if not isinstance(source, dict):
        raise ValueError("seed 9004 provenance has no source object")

    return {
        "replay_case_id": "seed9004",
        "scenario_id": "quotation_workflow_1",
        "source_repository": str(source.get("repository", "")),
        "source_branch": str(source.get("branch", "")),
        "source_commit_sha": str(source.get("commit_sha", "")),
        "provenance": provenance,
        "agent": agent.model_dump(mode="json"),
        "truth": truth.model_dump(mode="json"),
        "evaluation_context": context.model_dump(mode="json"),
        "knowledge_coverage": knowledge_coverage.model_dump(mode="json"),
        "expected": expected,
        "stakeholder_knowledge": None,
    }


def replay_inputs_from_store(
    replay_store: BusinessInterviewReplayStore,
) -> tuple[
    AgentGraph, BusinessProcessGraph, InterviewEvaluationContext, KnowledgeCoverageView
]:
    """Restore and validate the four authoritative scoring inputs."""
    agent = AgentGraph.model_validate(replay_store.agent)
    truth = BusinessProcessGraph.model_validate(replay_store.truth)
    validate_canonical_graph(truth)
    context = InterviewEvaluationContext.model_validate(replay_store.evaluation_context)
    knowledge_coverage = KnowledgeCoverageView.model_validate(
        replay_store.knowledge_coverage
    )
    return agent, truth, context, knowledge_coverage


__all__ = [
    "BusinessInterviewReplayStore",
    "load_seed9004_store_payload",
    "primary_evaluation_field_names",
    "replay_inputs_from_store",
]
