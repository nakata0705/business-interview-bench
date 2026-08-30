"""Shared Inspect scoring bridge for the unchanged 41-field core result."""

# The workspace-level auxiliary resolver may not see the Inspect dev group.
# Project-level ``uv run pyright`` is authoritative for this adapter.
# pyright: reportMissingImports=false

from __future__ import annotations

from dataclasses import asdict, fields
from typing import Any, cast

from inspect_ai.scorer import Score

from business_interview.evaluation import (
    KnowledgeCoverageView,
    PrimaryEvaluation,
    evaluate_primary,
)
from business_interview.models import (
    AgentGraph,
    BusinessProcessGraph,
    InterviewEvaluationContext,
)


def score_primary_inputs(
    agent: AgentGraph,
    truth: BusinessProcessGraph,
    context: InterviewEvaluationContext,
    knowledge_coverage: KnowledgeCoverageView,
) -> Score:
    """Delegate exactly once to ``evaluate_primary`` and preserve all fields."""
    result = evaluate_primary(agent, truth, context, knowledge_coverage)
    values: dict[str, Any] = asdict(result)
    field_names = tuple(field.name for field in fields(PrimaryEvaluation))
    if len(values) != len(field_names) or set(values) != set(field_names):
        raise ValueError(
            "evaluate_primary field contract changed: "
            f"expected {len(field_names)} fields {field_names!r}, "
            f"got {len(values)} fields {tuple(values)!r}"
        )
    return Score(value=cast(dict[str, str | int | float | bool | None], values))


__all__ = ["score_primary_inputs"]
