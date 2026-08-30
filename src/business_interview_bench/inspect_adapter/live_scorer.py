"""Deterministic scorer for completed (or explicitly incomplete) live sessions."""

# The workspace-level auxiliary resolver may not see the Inspect dev group.
# Project-level ``uv run pyright`` is authoritative for this adapter.
# pyright: reportMissingImports=false

from __future__ import annotations

from inspect_ai.scorer import Score, Scorer, Target, mean, scorer
from inspect_ai.solver import TaskState

from business_interview.evaluation import KnowledgeCoverageView
from business_interview.models import BusinessProcessGraph, validate_canonical_graph

from .live_store import BusinessInterviewLiveStore, load_live_state
from .primary_score import score_primary_inputs


@scorer({"reconstruction_pass": [mean()]}, name="phase13_primary_scorer")
def phase13_primary_scorer() -> Scorer:
    """Score the final live graph through the unchanged 41-field evaluator."""

    async def score(state: TaskState, target: Target) -> Score:
        del target
        store = state.store_as(BusinessInterviewLiveStore)
        runtime = load_live_state(store)
        truth = BusinessProcessGraph.model_validate(store.truth)
        validate_canonical_graph(truth)
        coverage = KnowledgeCoverageView.model_validate(store.knowledge_coverage)
        return score_primary_inputs(
            runtime.agent_graph,
            truth,
            runtime.evaluation_context(),
            coverage,
        )

    return score


# A shorter public alias for programmatic Task construction.
live_primary_scorer = phase13_primary_scorer


__all__ = ["live_primary_scorer", "phase13_primary_scorer"]
