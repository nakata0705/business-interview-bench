"""Pure business-only views of canonical Truth graphs."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from business_interview.models import (
    BusinessProcessGraph,
    TruthConcept,
    TruthEdge,
    TruthNode,
    business_edge_ids,
    business_entry_node_ids,
    business_exit_node_ids,
    business_node_ids,
    validate_canonical_graph,
)


@dataclass(frozen=True)
class BusinessGraphView:
    """Immutable, structural-element-free Truth view for comparison.

    The view retains the canonical Truth's business nodes, edges, concepts, and
    boundary-derived entry/exit IDs.  SOURCE/SINK nodes and their protected
    boundary edges are deliberately absent from the view, so callers cannot
    accidentally count them as business semantics.
    """

    id: str
    name: str
    nodes: Mapping[str, TruthNode]
    edges: Mapping[str, TruthEdge]
    concepts: Mapping[str, TruthConcept]
    start_node_ids: tuple[str, ...]
    end_node_ids: tuple[str, ...]

    @property
    def start_node_id(self) -> str | None:
        """Return the legacy single-entry convenience value when unambiguous."""
        return self.start_node_ids[0] if len(self.start_node_ids) == 1 else None


def business_graph_projection(
    truth: BusinessProcessGraph | BusinessGraphView,
) -> BusinessGraphView:
    """Return a pure business-only projection of canonical ``truth``.

    The input must already satisfy the Phase 2 canonical Truth contract.  The
    returned mappings and model values are deep copies behind read-only
    mapping views; neither the input graph nor its nested models are mutated.
    """
    if isinstance(truth, BusinessGraphView):
        return truth

    validate_canonical_graph(truth)
    node_ids = business_node_ids(truth)
    edge_ids = business_edge_ids(truth)
    concept_ids = sorted(truth.concepts)
    entries = tuple(business_entry_node_ids(truth))
    exits = tuple(business_exit_node_ids(truth))

    nodes = {
        node_id: truth.nodes[node_id].model_copy(deep=True) for node_id in node_ids
    }
    edges = {
        edge_id: truth.edges[edge_id].model_copy(deep=True) for edge_id in edge_ids
    }
    concepts = {
        concept_id: truth.concepts[concept_id].model_copy(deep=True)
        for concept_id in concept_ids
    }
    return BusinessGraphView(
        id=truth.id,
        name=truth.name,
        nodes=MappingProxyType(nodes),
        edges=MappingProxyType(edges),
        concepts=MappingProxyType(concepts),
        start_node_ids=entries,
        end_node_ids=exits,
    )


__all__ = ["BusinessGraphView", "business_graph_projection"]
