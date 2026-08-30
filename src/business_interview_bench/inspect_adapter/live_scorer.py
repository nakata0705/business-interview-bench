"""Deterministic scorer for completed (or explicitly incomplete) live sessions."""

# The workspace-level auxiliary resolver may not see the Inspect dev group.
# Project-level ``uv run pyright`` is authoritative for this adapter.
# pyright: reportMissingImports=false

from __future__ import annotations

from inspect_ai.scorer import Score, Scorer, Target, mean, scorer
from inspect_ai.solver import TaskState

from business_interview.evaluation import KnowledgeCoverageView
from business_interview.models import BusinessProcessGraph, validate_canonical_graph
from business_interview.stakeholders import (
    StakeholderKnowledge,
    StakeholderProfile,
    knowledge_coverage_view,
    project_knowledge,
)

from .live_store import BusinessInterviewLiveStore, load_live_state
from .primary_score import score_primary_inputs


def _load_validated_stakeholder_knowledge(
    store: BusinessInterviewLiveStore,
    truth: BusinessProcessGraph,
    coverage: KnowledgeCoverageView,
) -> StakeholderKnowledge | None:
    """Validate persisted exact knowledge and optional projection provenance."""
    if not store.stakeholder_knowledge:
        if store.stakeholder_profile or store.stakeholder_seed is not None:
            raise ValueError(
                "stakeholder projection metadata requires exact stakeholder knowledge"
            )
        return None
    knowledge = StakeholderKnowledge.model_validate(store.stakeholder_knowledge)
    if store.stakeholder_profile:
        if store.stakeholder_seed is None:
            raise ValueError(
                "stored stakeholder profile is missing its projection seed"
            )
        profile = StakeholderProfile.model_validate(store.stakeholder_profile)
        projected = project_knowledge(truth, profile, seed=store.stakeholder_seed)
        if projected != knowledge:
            raise ValueError(
                "stored StakeholderKnowledge does not match profile and seed"
            )
    if knowledge_coverage_view(truth, knowledge) != coverage:
        raise ValueError(
            "stored knowledge coverage does not match exact StakeholderKnowledge"
        )
    return knowledge


def _validated_terminology_terms(
    store: BusinessInterviewLiveStore,
    knowledge: StakeholderKnowledge | None,
) -> dict[str, list[str]]:
    """Translate validated private terminology into evaluator term hints."""
    if knowledge is None:
        return {}
    terms: dict[str, set[str]] = {}
    runtime = load_live_state(store)
    for entry in runtime.semantic_ledger.entries:
        for event in entry.terminology:
            concept = knowledge.graph.concepts.get(event.semantic_id)
            if concept is None:
                raise ValueError(
                    "stored terminology references an unknown stakeholder concept"
                )
            terms.setdefault(concept.truth_concept_id, set()).add(event.proposed_term)
    return {truth_id: sorted(values) for truth_id, values in sorted(terms.items())}


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
        knowledge = _load_validated_stakeholder_knowledge(store, truth, coverage)
        return score_primary_inputs(
            runtime.agent_graph,
            truth,
            runtime.evaluation_context(),
            coverage,
            terminology_terms=_validated_terminology_terms(store, knowledge),
        )

    return score


# A shorter public alias for programmatic Task construction.
live_primary_scorer = phase13_primary_scorer


__all__ = ["live_primary_scorer", "phase13_primary_scorer"]
