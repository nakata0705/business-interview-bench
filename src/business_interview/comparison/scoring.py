"""Source-compatible graph/content score arithmetic."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from business_interview.models import (
    AbsentType,
    AgentGraph,
    BusinessProcessGraph,
    ConceptRef,
    UnsetType,
    business_edge_ids,
    business_node_ids,
)

from .projection import BusinessGraphView, business_graph_projection

_NODE_PROPS = ("activity", "actor", "system", "reads", "writes", "rationale")


def slot_value(node: Any, property_name: str) -> Any:
    """Read a Truth or Agent slot using the shared rationale spelling."""
    return node.slot_value(property_name)


def _truth_scalar_value(value: object) -> str | None:
    if isinstance(value, ConceptRef):
        return value.concept_id
    return None


def score_scalar_slot(
    agent_value: object,
    truth_value: object,
    agent_to_truth: Mapping[str, str],
    *,
    known_absent: Callable[[object], bool] | None = None,
) -> int:
    """Score one scalar slot using the Agent four-state contract."""
    truth_concept_id = _truth_scalar_value(truth_value)
    if truth_concept_id is not None:
        if not isinstance(agent_value, ConceptRef) or not agent_value.asserted:
            return 0
        return (
            1
            if agent_value.concept_id in agent_to_truth
            and agent_to_truth[agent_value.concept_id] == truth_concept_id
            else 0
        )
    if isinstance(agent_value, AbsentType):
        return 1
    if known_absent is not None and known_absent(agent_value):
        return 1
    return 0


def score_list_slot(
    agent_value: object,
    truth_value: object,
    agent_to_truth: Mapping[str, str],
    *,
    known_absent: Callable[[object], bool] | None = None,
) -> tuple[float, int]:
    """Return source-compatible list score and unsupported-reference count."""
    expected = (
        {ref.concept_id for ref in truth_value}
        if isinstance(truth_value, list)
        else set()
    )
    if not expected:
        if isinstance(agent_value, AbsentType):
            return 1.0, 0
        if known_absent is not None and known_absent(agent_value):
            return 1.0, 0
        if isinstance(agent_value, list):
            unsupported = sum(
                1 for ref in agent_value if isinstance(ref, ConceptRef) and ref.asserted
            )
            return 0.0, unsupported
        return 0.0, 0
    if not isinstance(agent_value, list):
        return 0.0, 0
    claimed = {
        concept_id
        for ref in agent_value
        if isinstance(ref, ConceptRef)
        and ref.asserted
        and (concept_id := agent_to_truth.get(ref.concept_id)) is not None
    }
    if not claimed:
        return 0.0, 0
    recall = len(claimed & expected) / len(expected)
    precision = len(claimed & expected) / len(claimed)
    unsupported = sum(
        1
        for ref in agent_value
        if isinstance(ref, ConceptRef)
        and ref.asserted
        and agent_to_truth.get(ref.concept_id) is None
    )
    return recall * precision, unsupported


@dataclass(frozen=True)
class AlignedGraphComparison:
    """Graph/content metrics after explicit concept/node/edge alignment."""

    graph_created: bool
    graph_valid: bool
    node_recall: float
    node_precision: float
    edge_recall: float
    edge_precision: float
    start_correct: bool
    end_recall: float
    end_precision: float
    activity_correctness: float
    actor_correctness: float
    system_correctness: float
    read_correctness: float
    write_correctness: float
    rationale_correctness: float
    condition_correctness: float
    concept_correctness: float
    concept_recall: float
    concept_precision: float
    unsupported_ref_count: int
    fabricated_node_count: int
    fabricated_edge_count: int
    glossary_complete: bool


def _agent_graph_valid(agent: AgentGraph) -> bool:
    """Match the source graph-validity rule without changing Phase 2 models."""
    return bool(
        agent.is_valid
        and all(
            not isinstance(node.activity, UnsetType) for node in agent.nodes.values()
        )
    )


def compare_aligned_graphs(
    agent: AgentGraph | None = None,
    truth: BusinessProcessGraph | BusinessGraphView | None = None,
    alignment: Any | None = None,
    *,
    candidate: AgentGraph | None = None,
    graph_valid: bool | None = None,
    known_absent: Callable[[object], bool] | None = None,
    candidate_node_ids: list[str] | None = None,
    candidate_edge_ids: list[str] | None = None,
    candidate_start_node_ids: set[str] | None = None,
    candidate_end_node_ids: set[str] | None = None,
    truth_entry_node_ids: set[str] | None = None,
    empty_node_recall: float = 0.0,
) -> AlignedGraphComparison:
    """Compare aligned Agent and canonical Truth business graphs.

    ``candidate=`` is accepted as a source-compatible alias for ``agent``.
    Structural SOURCE/SINK elements are projected out before every denominator,
    endpoint comparison, and edge comparison.  Only graph/content metrics are
    returned; evidence, protocol, knowledge, and evaluator facades are outside
    this Phase 4 core.
    """
    if agent is None:
        agent = candidate
    if agent is None:
        raise TypeError("compare_aligned_graphs() requires an AgentGraph")
    if truth is None:
        raise TypeError("compare_aligned_graphs() requires a TruthGraph")
    if alignment is None:
        raise TypeError("compare_aligned_graphs() requires a GraphAlignment")
    truth_view = business_graph_projection(truth)
    candidate_node_ids = (
        sorted(set(candidate_node_ids))
        if candidate_node_ids is not None
        else business_node_ids(agent)
    )
    candidate_edge_ids = (
        sorted(set(candidate_edge_ids))
        if candidate_edge_ids is not None
        else business_edge_ids(agent)
    )
    candidate_start_node_ids = (
        set(candidate_start_node_ids)
        if candidate_start_node_ids is not None
        else set(agent.start_node_ids)
    )
    candidate_end_node_ids = (
        set(candidate_end_node_ids)
        if candidate_end_node_ids is not None
        else set(agent.end_node_ids)
    )
    truth_entry_node_ids = (
        set(truth_entry_node_ids)
        if truth_entry_node_ids is not None
        else set(truth_view.start_node_ids)
    )
    truth_end_node_ids = set(truth_view.end_node_ids)

    node_mapping = alignment.node_to_truth
    edge_mapping = alignment.edge_to_truth
    concept_mapping = alignment.concept_to_truth
    if len(edge_mapping) != len(set(edge_mapping.values())):
        raise ValueError("compare_aligned_graphs(): edge alignment must be one-to-one")

    target_node_ids = list(truth_view.nodes)
    matched_nodes = set(node_mapping.values())
    node_recall = (
        len(matched_nodes) / len(target_node_ids)
        if target_node_ids
        else empty_node_recall
    )
    node_precision = (
        len(node_mapping) / len(candidate_node_ids) if candidate_node_ids else 0.0
    )
    fabricated_node_count = len(candidate_node_ids) - len(node_mapping)

    target_edge_ids = list(truth_view.edges)
    matched_edges = set(edge_mapping.values())
    edge_recall = len(matched_edges) / len(target_edge_ids) if target_edge_ids else 1.0
    edge_precision = (
        len(edge_mapping) / len(candidate_edge_ids) if candidate_edge_ids else 0.0
    )
    fabricated_edge_count = len(candidate_edge_ids) - len(edge_mapping)

    mapped_starts = {
        node_mapping[node_id]
        for node_id in candidate_start_node_ids
        if node_id in node_mapping
    }
    start_correct = mapped_starts == truth_entry_node_ids
    mapped_ends = {
        node_mapping[node_id]
        for node_id in candidate_end_node_ids
        if node_id in node_mapping
    }
    end_recall = (
        len(mapped_ends & truth_end_node_ids) / len(truth_end_node_ids)
        if truth_end_node_ids
        else 1.0
    )
    end_precision = (
        len(mapped_ends & truth_end_node_ids) / len(mapped_ends) if mapped_ends else 0.0
    )

    hits = {property_name: 0.0 for property_name in _NODE_PROPS}
    unsupported = 0
    for candidate_id, truth_id in node_mapping.items():
        candidate_node = agent.nodes[candidate_id]
        truth_node = truth_view.nodes[truth_id]
        for property_name in _NODE_PROPS:
            candidate_value = slot_value(candidate_node, property_name)
            truth_value = slot_value(truth_node, property_name)
            if property_name in ("reads", "writes"):
                score, unsupported_here = score_list_slot(
                    candidate_value,
                    truth_value,
                    concept_mapping,
                    known_absent=known_absent,
                )
                hits[property_name] += score
                unsupported += unsupported_here
            else:
                hits[property_name] += score_scalar_slot(
                    candidate_value,
                    truth_value,
                    concept_mapping,
                    known_absent=known_absent,
                )
    denominator = len(node_mapping) or 1

    candidate_edge_by_truth = {
        truth_edge_id: agent.edges[agent_edge_id]
        for agent_edge_id, truth_edge_id in edge_mapping.items()
    }
    condition_hits = 0
    for truth_edge_id in target_edge_ids:
        candidate_edge = candidate_edge_by_truth.get(truth_edge_id)
        if candidate_edge is None:
            continue
        if score_scalar_slot(
            candidate_edge.condition,
            truth_view.edges[truth_edge_id].condition,
            concept_mapping,
            known_absent=known_absent,
        ):
            condition_hits += 1
    condition_correctness = (
        condition_hits / len(target_edge_ids) if target_edge_ids else 1.0
    )

    concept_correctness = alignment.concept_recall * alignment.concept_precision
    glossary_complete = bool(
        alignment.concept_recall == 1.0 and alignment.concept_precision == 1.0
    )
    return AlignedGraphComparison(
        graph_created=bool(candidate_node_ids),
        graph_valid=_agent_graph_valid(agent) if graph_valid is None else graph_valid,
        node_recall=node_recall,
        node_precision=node_precision,
        edge_recall=edge_recall,
        edge_precision=edge_precision,
        start_correct=start_correct,
        end_recall=end_recall,
        end_precision=end_precision,
        activity_correctness=hits["activity"] / denominator,
        actor_correctness=hits["actor"] / denominator,
        system_correctness=hits["system"] / denominator,
        read_correctness=hits["reads"] / denominator,
        write_correctness=hits["writes"] / denominator,
        rationale_correctness=hits["rationale"] / denominator,
        condition_correctness=condition_correctness,
        concept_correctness=concept_correctness,
        concept_recall=alignment.concept_recall,
        concept_precision=alignment.concept_precision,
        unsupported_ref_count=unsupported,
        fabricated_node_count=fabricated_node_count,
        fabricated_edge_count=fabricated_edge_count,
        glossary_complete=glossary_complete,
    )


__all__ = [
    "AlignedGraphComparison",
    "compare_aligned_graphs",
    "score_list_slot",
    "score_scalar_slot",
    "slot_value",
]
