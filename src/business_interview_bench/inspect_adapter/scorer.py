"""Inspect scorer that delegates to the 41-field core evaluator."""

# The workspace-level auxiliary resolver may not see the Inspect dev group.
# Project-level ``uv run pyright`` remains the authoritative adapter check.
# pyright: reportMissingImports=false

from __future__ import annotations

from inspect_ai.scorer import Score, Scorer, Target, mean, scorer
from inspect_ai.solver import TaskState

from business_interview.evaluation import KnowledgeCoverageView
from business_interview.models import (
    AgentGraph,
    BusinessProcessGraph,
    InterviewEvaluationContext,
    validate_canonical_graph,
)

from .live_scorer import live_primary_scorer, phase13_primary_scorer
from .primary_score import score_primary_inputs
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
        return score_primary_inputs(agent, truth, context, knowledge_coverage)

    return score


__all__ = [
    "live_primary_scorer",
    "phase13_primary_scorer",
    "primary_scorer",
]
