"""Minimal Truth-addressed input and arithmetic for knowledge coverage."""

# The workspace-level auxiliary Pyright runner can miss freshly added sibling
# modules; project-level ``uv run pyright`` remains the authoritative check.
# pyright: reportMissingImports=false

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from business_interview.models import (
    BusinessProcessGraph,
    ConceptRef,
    TruthNode,
    business_edge_ids,
    business_node_ids,
)

CoverageScalarState = Literal["known", "dont_know"]
CoverageListState = Literal["known_absent", "dont_know", "known_values"]


class CoverageListSlot(BaseModel):
    """The three list states needed by source coverage arithmetic.

    ``known_absent`` corresponds to source ``None`` and consequently counts
    every expected Truth list element as known. ``known_values`` stores Truth
    concept IDs directly, so no stakeholder-local concept mapping is needed.
    """

    model_config = ConfigDict(frozen=True)

    state: CoverageListState = "known_absent"
    truth_concept_ids: tuple[str, ...] = Field(default_factory=tuple)


class CoverageNode(BaseModel):
    """Truth-addressed node knowledge required by ``knowledge_coverage``."""

    model_config = ConfigDict(frozen=True)

    truth_node_id: str
    activity: CoverageScalarState = "known"
    actor: CoverageScalarState = "known"
    system: CoverageScalarState = "known"
    reads: CoverageListSlot = Field(default_factory=CoverageListSlot)
    writes: CoverageListSlot = Field(default_factory=CoverageListSlot)
    rationale: CoverageScalarState = "known"

    def slot_value(self, property_name: str) -> CoverageScalarState | CoverageListSlot:
        """Read a coverage slot using the evaluator's public property names."""
        return getattr(self, property_name)


class CoverageEdge(BaseModel):
    """Truth-addressed edge knowledge required by source coverage."""

    model_config = ConfigDict(frozen=True)

    truth_edge_id: str
    condition: CoverageScalarState = "known"


class KnowledgeCoverageView(BaseModel):
    """Minimal read-only, Truth-addressed knowledge coverage view.

    Missing entries mean that the stakeholder does not know the corresponding
    Truth node or edge exists. Extra entries are retained as input data but are
    ignored by the source-compatible Truth iteration.
    """

    model_config = ConfigDict(frozen=True)

    nodes_by_truth_id: dict[str, CoverageNode] = Field(default_factory=dict)
    edges_by_truth_id: dict[str, CoverageEdge] = Field(default_factory=dict)


def _truth_list(value: object) -> list[ConceptRef]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, ConceptRef)]


def evaluate_knowledge_coverage(
    truth: BusinessProcessGraph,
    knowledge: KnowledgeCoverageView | None,
) -> float:
    """Return source-compatible coverage over business Truth addresses."""
    if truth is None or knowledge is None:
        return 0.0

    total = known = 0
    for node_id in business_node_ids(truth):
        truth_node: TruthNode = truth.nodes[node_id]
        coverage_node = knowledge.nodes_by_truth_id.get(node_id)
        total += 1
        if coverage_node is not None:
            known += 1

        for property_name in (
            "activity",
            "actor",
            "system",
            "reads",
            "writes",
            "rationale",
        ):
            total += 1
            expected = _truth_list(truth_node.slot_value(property_name))
            if coverage_node is None:
                if property_name in ("reads", "writes"):
                    total += len(expected)
                continue

            value = coverage_node.slot_value(property_name)
            if property_name not in ("reads", "writes"):
                if value != "dont_know":
                    known += 1
                continue

            if not isinstance(value, CoverageListSlot):
                raise TypeError("coverage list slot must be a CoverageListSlot")
            if value.state != "dont_know":
                # This is the source's slot-level known count: None and a
                # known list both count here, while DONT_KNOW does not.
                known += 1
            for expected_ref in expected:
                total += 1
                if value.state == "dont_know":
                    continue
                if value.state == "known_absent":
                    known += 1
                elif value.state == "known_values" and expected_ref.concept_id in set(
                    value.truth_concept_ids
                ):
                    known += 1

    for edge_id in business_edge_ids(truth):
        coverage_edge = knowledge.edges_by_truth_id.get(edge_id)
        total += 1
        if coverage_edge is not None:
            known += 1
        total += 1
        if coverage_edge is not None and coverage_edge.condition != "dont_know":
            known += 1

    return known / total if total else 0.0


def knowledge_coverage_view(
    truth: BusinessProcessGraph,
    knowledge: Any,
) -> KnowledgeCoverageView:
    """Derive coverage from a stakeholder-private projection.

    The import is intentionally lazy so the evaluator package does not depend
    on stakeholder projection at module import time.  The implementation and
    validation authority remains in the stakeholder domain package.
    """
    from business_interview.stakeholders.projection import (
        knowledge_coverage_view as derive_view,
    )

    return derive_view(truth, knowledge)


# Keep the source spelling available while exposing a descriptive public name.
knowledge_coverage = evaluate_knowledge_coverage


__all__ = [
    "CoverageEdge",
    "CoverageListSlot",
    "CoverageNode",
    "CoverageScalarState",
    "KnowledgeCoverageView",
    "evaluate_knowledge_coverage",
    "knowledge_coverage",
    "knowledge_coverage_view",
]
