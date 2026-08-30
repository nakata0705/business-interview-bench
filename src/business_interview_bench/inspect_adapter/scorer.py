"""Inspect scorer that delegates to the 41-field core evaluator."""

# The workspace-level auxiliary resolver may not see the Inspect dev group.
# Project-level ``uv run pyright`` remains the authoritative adapter check.
# pyright: reportMissingImports=false

from __future__ import annotations

from dataclasses import asdict, fields
from typing import Any, cast

from inspect_ai.scorer import Score, Scorer, Target, mean, scorer
from inspect_ai.solver import TaskState

from business_interview.evaluation import (
    KnowledgeCoverageView,
    PrimaryEvaluation,
    evaluate_primary,
)
from business_interview.models import (
    AgentGraph,
    BusinessProcessGraph,
    InterviewEvaluationContext,
    validate_canonical_graph,
)

from .store import BusinessInterviewReplayStore


@scorer({"reconstruction_pass": [mean()]}, name="primary_scorer")
def primary_scorer() -> Scorer:
    """Score exact Store inputs using only ``evaluate_primary``."""

    async def score(state: TaskState, target: Target) -> Score:
        del target  # required by Inspect's Scorer protocol; replay has no target
        replay_store = state.store_as(BusinessInterviewReplayStore)
        agent = AgentGraph.model_validate(replay_store.agent)
        truth = BusinessProcessGraph.model_validate(replay_store.truth)
        validate_canonical_graph(truth)
        context = InterviewEvaluationContext.model_validate(
            replay_store.evaluation_context
        )
        knowledge_coverage = KnowledgeCoverageView.model_validate(
            replay_store.knowledge_coverage
        )
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

    return score


__all__ = ["primary_scorer"]
