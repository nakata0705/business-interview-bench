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


class BusinessInterviewLiveStore(StoreModel):
    """JSON-only Inspect persistence for a live interview.

    ``live_state`` contains the core runtime, including the private semantic
    ledger.  It is not automatically sent to the candidate; only the solver's
    public ``TaskState.messages`` and graph-tool results are model input.
    Truth and coverage are retained separately for final deterministic scoring,
    never exposed by candidate tools.
    """

    live_state: dict[str, Any] = Field(default_factory=dict)
    truth: dict[str, Any] = Field(default_factory=dict)
    knowledge_coverage: dict[str, Any] = Field(default_factory=dict)

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
    def stakeholder_turns(self) -> int:
        return self.runtime.stakeholder_turns


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
) -> None:
    """Persist only deterministic final-evaluation inputs outside core state."""
    store.truth = truth.model_dump(mode="json")
    store.knowledge_coverage = knowledge_coverage.model_dump(mode="json")


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
