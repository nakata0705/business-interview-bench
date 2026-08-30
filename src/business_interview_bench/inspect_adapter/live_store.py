"""Inspect Store bridge for the core :mod:`business_interview.runtime` state."""

# The workspace-level auxiliary resolver may not see the Inspect dev group.
# Project-level ``uv run pyright`` is authoritative for this adapter.
# pyright: reportMissingImports=false

from __future__ import annotations

from typing import Any

from inspect_ai.util import StoreModel
from pydantic import Field

from business_interview.evaluation import KnowledgeCoverageView
from business_interview.models import BusinessProcessGraph
from business_interview.runtime import LiveInterviewStore
from business_interview.stakeholders import (
    StakeholderKnowledge,
    StakeholderProfile,
    validate_stakeholder_knowledge,
)


class BusinessInterviewLiveStore(StoreModel):
    """JSON-only Inspect persistence for a live interview.

    ``live_state`` contains the core runtime, including the private semantic
    ledger.  It is not automatically sent to the candidate; only the solver's
    public ``TaskState.messages`` and graph-tool results are model input.
    Truth, coverage, and exact stakeholder setup are retained separately for
    final deterministic scoring, never exposed by candidate tools.
    """

    live_state: dict[str, Any] = Field(default_factory=dict)
    truth: dict[str, Any] = Field(default_factory=dict)
    knowledge_coverage: dict[str, Any] = Field(default_factory=dict)
    # These fields are evaluator-private Store JSON.  They are deliberately
    # separate from live_state and are never returned by candidate tools.
    stakeholder_profile: dict[str, Any] = Field(default_factory=dict)
    stakeholder_seed: int | None = None
    stakeholder_knowledge: dict[str, Any] = Field(default_factory=dict)

    @property
    def runtime(self) -> LiveInterviewStore:
        return load_live_state(self)

    @property
    def scenario_id(self) -> str:
        return self.runtime.scenario_id

    @property
    def agent_graph(self):
        return self.runtime.agent_graph

    @property
    def observations(self):
        return self.runtime.observations

    @property
    def semantic_ledger(self):
        return self.runtime.semantic_ledger

    @property
    def protocol_state(self):
        return self.runtime.protocol_state

    @property
    def candidate_turns(self) -> int:
        return self.runtime.candidate_turns

    @property
    def candidate_steps(self) -> int:
        return self.runtime.candidate_steps

    @property
    def stakeholder_turns(self) -> int:
        return self.runtime.stakeholder_turns

    @property
    def projection_seed(self) -> int | None:
        """Descriptive alias for the persisted stakeholder projection seed."""
        return self.stakeholder_seed


def persist_live_state(
    store: BusinessInterviewLiveStore,
    runtime: LiveInterviewStore,
) -> None:
    """Persist core state as ordinary JSON-compatible data."""
    store.live_state = runtime.model_dump(mode="json")


def load_live_state(store: BusinessInterviewLiveStore) -> LiveInterviewStore:
    """Reconstruct core state from the Inspect Store payload."""
    if not store.live_state:
        raise ValueError("Inspect live Store has no live_state")
    return LiveInterviewStore.model_validate(store.live_state)


def persist_evaluation_inputs(
    store: BusinessInterviewLiveStore,
    truth: BusinessProcessGraph,
    knowledge_coverage: KnowledgeCoverageView,
    *,
    stakeholder_knowledge: StakeholderKnowledge | None = None,
    stakeholder_profile: StakeholderProfile | None = None,
    stakeholder_seed: int | None = None,
) -> None:
    """Persist evaluator inputs and exact private stakeholder provenance.

    The exact projected knowledge is stored even when a profile and seed are
    available: it makes replay independent of future projection code changes.
    """
    store.truth = truth.model_dump(mode="json")
    store.knowledge_coverage = knowledge_coverage.model_dump(mode="json")
    if stakeholder_profile is not None:
        store.stakeholder_profile = stakeholder_profile.model_dump(mode="json")
    if stakeholder_seed is not None:
        store.stakeholder_seed = stakeholder_seed
    if stakeholder_knowledge is not None:
        validate_stakeholder_knowledge(stakeholder_knowledge)
        store.stakeholder_knowledge = stakeholder_knowledge.model_dump(mode="json")
        if stakeholder_seed is None:
            store.stakeholder_seed = stakeholder_knowledge.generation_seed


# A descriptive alias is useful for callers that do not want the package name
# in their import.
LiveInterviewInspectStore = BusinessInterviewLiveStore
InspectLiveInterviewStore = BusinessInterviewLiveStore
LiveInterviewStoreModel = BusinessInterviewLiveStore


__all__ = [
    "BusinessInterviewLiveStore",
    "InspectLiveInterviewStore",
    "LiveInterviewInspectStore",
    "LiveInterviewStoreModel",
    "load_live_state",
    "persist_evaluation_inputs",
    "persist_live_state",
]
