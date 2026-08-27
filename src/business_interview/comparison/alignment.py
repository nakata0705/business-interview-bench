"""Deterministic Agent node/edge alignment after concept alignment."""

# The project-level uv Pyright configuration resolves these local modules;
# this directive also quiets the workspace-level auxiliary resolver.
# pyright: reportMissingImports=false

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from business_interview.models import (
    AgentGraph,
    BusinessProcessGraph,
    ConceptRef,
    business_edge_ids,
    business_entry_node_ids,
    business_exit_node_ids,
    business_node_ids,
)

from .assignment import assignment_score, bipartite_components, max_weight_assignment
from .concepts import ConceptAlignment, align_concepts
from .projection import BusinessGraphView, business_graph_projection
from .scoring import score_list_slot, score_scalar_slot

_NODE_PROPS = ("activity", "actor", "system", "reads", "writes", "rationale")
_NODE_WL_ROUND_LIMIT = 12
_NODE_AMBIGUITY_CLASS_LIMIT = 8
_NODE_MATCH_CARDINALITY_BONUS = 100.0
_NODE_MATCH_ACTIVITY_WEIGHT = 8.0
_NODE_MATCH_ATTRIBUTE_WEIGHTS = {
    "actor": 2.0,
    "system": 2.0,
    "reads": 1.0,
    "writes": 1.0,
    "rationale": 0.5,
}
_EDGE_CARDINALITY_WEIGHT = 2.0


@dataclass(frozen=True)
class GraphAlignment:
    """Explicit local concept, node, and edge mappings plus concept scores."""

    concept_to_truth: dict[str, str]
    node_to_truth: dict[str, str]
    edge_to_truth: dict[str, str]
    concept_recall: float
    concept_precision: float


@dataclass(frozen=True)
class _TopologyData:
    node_ids: tuple[str, ...]
    predecessors: dict[str, tuple[str, ...]]
    successors: dict[str, tuple[str, ...]]
    base_profiles: dict[str, tuple[Any, ...]]
    topology_known: bool


@dataclass(frozen=True)
class _TopologyFingerprint:
    base_profile: tuple[Any, ...]
    refinement_colors: tuple[str, ...]
    topology_known: bool


def _topology_distances(
    starts: set[str], adjacency: dict[str, tuple[str, ...]]
) -> dict[str, int]:
    distances = {node_id: 0 for node_id in sorted(starts)}
    queue = sorted(starts)
    index = 0
    while index < len(queue):
        node_id = queue[index]
        index += 1
        for neighbor in sorted(adjacency.get(node_id, ())):
            if neighbor not in distances:
                distances[neighbor] = distances[node_id] + 1
                queue.append(neighbor)
    return distances


def _declared_entries(graph: Any) -> set[str]:
    entries: set[str] = set()
    if isinstance(graph, BusinessGraphView):
        entries.update(graph.start_node_ids)
    else:
        entries.update(business_entry_node_ids(graph))
    entries.update(getattr(graph, "start_node_ids", ()))
    start_node_id = getattr(graph, "start_node_id", None)
    if start_node_id is not None:
        entries.add(start_node_id)
    return entries


def _declared_exits(graph: Any) -> set[str]:
    exits: set[str] = set()
    if isinstance(graph, BusinessGraphView):
        exits.update(graph.end_node_ids)
    else:
        exits.update(business_exit_node_ids(graph))
    exits.update(getattr(graph, "end_node_ids", ()))
    return exits


def _topology_data(graph: Any) -> _TopologyData:
    """Build an ID-free local structural profile for each business node."""
    node_ids = tuple(business_node_ids(graph))
    node_set = set(node_ids)
    predecessors = {node_id: [] for node_id in node_ids}
    successors = {node_id: [] for node_id in node_ids}
    for edge_id in business_edge_ids(graph):
        edge = graph.edges[edge_id]
        if edge.from_node not in node_set or edge.to_node not in node_set:
            continue
        successors[edge.from_node].append(edge.to_node)
        predecessors[edge.to_node].append(edge.from_node)

    predecessor_tuples = {
        node_id: tuple(sorted(values)) for node_id, values in predecessors.items()
    }
    successor_tuples = {
        node_id: tuple(sorted(values)) for node_id, values in successors.items()
    }
    entries = _declared_entries(graph) & node_set
    entries.update(node_id for node_id in node_ids if not predecessor_tuples[node_id])
    exits = _declared_exits(graph) & node_set
    exits.update(node_id for node_id in node_ids if not successor_tuples[node_id])

    from_entry = _topology_distances(entries, successor_tuples)
    to_exit = _topology_distances(exits, predecessor_tuples)
    base_profiles: dict[str, tuple[Any, ...]] = {}
    for node_id in node_ids:
        predecessors_for_node = predecessor_tuples[node_id]
        successors_for_node = successor_tuples[node_id]
        predecessor_count = len(set(predecessors_for_node))
        successor_count = len(set(successors_for_node))
        self_loop_count = sum(neighbor == node_id for neighbor in successors_for_node)
        base_profiles[node_id] = (
            "entry" if node_id in entries else "non_entry",
            "exit" if node_id in exits else "non_exit",
            "merge" if predecessor_count > 1 else "non_merge",
            "branch" if successor_count > 1 else "non_branch",
            predecessor_count,
            successor_count,
            bool(self_loop_count),
            from_entry.get(node_id, -1),
            to_exit.get(node_id, -1),
        )
    explicit_boundary = bool(
        getattr(graph, "start_node_id", None)
        or getattr(graph, "start_node_ids", ())
        or getattr(graph, "end_node_ids", ())
    )
    return _TopologyData(
        node_ids=node_ids,
        predecessors=predecessor_tuples,
        successors=successor_tuples,
        base_profiles=base_profiles,
        topology_known=bool(business_edge_ids(graph)) or explicit_boundary,
    )


def _canonical_color_map(payloads: list[Any]) -> dict[Any, str]:
    return {
        payload: f"color_{index}"
        for index, payload in enumerate(sorted(set(payloads), key=repr))
    }


def _topology_fingerprints(
    agent: AgentGraph,
    truth: BusinessGraphView,
) -> tuple[dict[str, _TopologyFingerprint], dict[str, _TopologyFingerprint]]:
    """Return shared-round WL-style fingerprints for both business graphs."""
    agent_data = _topology_data(agent)
    truth_data = _topology_data(truth)
    node_count = max(len(agent_data.node_ids), len(truth_data.node_ids))
    rounds = min(_NODE_WL_ROUND_LIMIT, max(1, node_count))
    base_payloads = [
        ("base", profile)
        for data in (agent_data, truth_data)
        for profile in data.base_profiles.values()
    ]
    colors = _canonical_color_map(base_payloads)
    agent_colors = {
        node_id: colors[("base", agent_data.base_profiles[node_id])]
        for node_id in agent_data.node_ids
    }
    truth_colors = {
        node_id: colors[("base", truth_data.base_profiles[node_id])]
        for node_id in truth_data.node_ids
    }
    agent_color_history = {
        node_id: [agent_colors[node_id]] for node_id in agent_data.node_ids
    }
    truth_color_history = {
        node_id: [truth_colors[node_id]] for node_id in truth_data.node_ids
    }
    for _ in range(rounds):
        agent_payloads = {
            node_id: (
                agent_colors[node_id],
                tuple(
                    sorted(
                        agent_colors[neighbor]
                        for neighbor in agent_data.predecessors[node_id]
                    )
                ),
                tuple(
                    sorted(
                        agent_colors[neighbor]
                        for neighbor in agent_data.successors[node_id]
                    )
                ),
            )
            for node_id in agent_data.node_ids
        }
        truth_payloads = {
            node_id: (
                truth_colors[node_id],
                tuple(
                    sorted(
                        truth_colors[neighbor]
                        for neighbor in truth_data.predecessors[node_id]
                    )
                ),
                tuple(
                    sorted(
                        truth_colors[neighbor]
                        for neighbor in truth_data.successors[node_id]
                    )
                ),
            )
            for node_id in truth_data.node_ids
        }
        color_map = _canonical_color_map(
            list(agent_payloads.values()) + list(truth_payloads.values())
        )
        next_agent_colors = {
            node_id: color_map[payload] for node_id, payload in agent_payloads.items()
        }
        next_truth_colors = {
            node_id: color_map[payload] for node_id, payload in truth_payloads.items()
        }
        stable = next_agent_colors == agent_colors and next_truth_colors == truth_colors
        agent_colors = next_agent_colors
        truth_colors = next_truth_colors
        for node_id in agent_data.node_ids:
            agent_color_history[node_id].append(agent_colors[node_id])
        for node_id in truth_data.node_ids:
            truth_color_history[node_id].append(truth_colors[node_id])
        if stable:
            break

    agent_fingerprints = {
        node_id: _TopologyFingerprint(
            base_profile=agent_data.base_profiles[node_id],
            refinement_colors=tuple(agent_color_history[node_id]),
            topology_known=agent_data.topology_known,
        )
        for node_id in agent_data.node_ids
    }
    truth_fingerprints = {
        node_id: _TopologyFingerprint(
            base_profile=truth_data.base_profiles[node_id],
            refinement_colors=tuple(truth_color_history[node_id]),
            topology_known=truth_data.topology_known,
        )
        for node_id in truth_data.node_ids
    }
    return agent_fingerprints, truth_fingerprints


def _topology_similarity(
    agent_fingerprint: _TopologyFingerprint,
    truth_fingerprint: _TopologyFingerprint,
) -> float:
    """Return a topology bonus without rejecting an activity candidate."""
    if not agent_fingerprint.topology_known or not truth_fingerprint.topology_known:
        return 0.0
    profile_total = max(
        len(agent_fingerprint.base_profile), len(truth_fingerprint.base_profile)
    )
    profile_similarity = (
        sum(
            agent_value == truth_value
            for agent_value, truth_value in zip(
                agent_fingerprint.base_profile, truth_fingerprint.base_profile
            )
        )
        / profile_total
        if profile_total
        else 1.0
    )
    color_total = max(
        len(agent_fingerprint.refinement_colors),
        len(truth_fingerprint.refinement_colors),
    )
    color_similarity = (
        sum(
            agent_color == truth_color
            for agent_color, truth_color in zip(
                agent_fingerprint.refinement_colors,
                truth_fingerprint.refinement_colors,
            )
        )
        / color_total
        if color_total
        else 1.0
    )
    return (profile_similarity + color_similarity) / 2.0


def _node_attribute_weight(
    agent_node: Any,
    truth_node: Any,
    agent_to_truth: dict[str, str],
    topology_similarity: float,
) -> float | None:
    """Score aligned attributes for one topology candidate."""
    agent_activity = agent_node.slot_value("activity")
    truth_activity = truth_node.slot_value("activity")
    if not (
        isinstance(agent_activity, ConceptRef)
        and agent_activity.asserted
        and isinstance(truth_activity, ConceptRef)
        and truth_activity.asserted
    ):
        return None
    activity_score = score_scalar_slot(agent_activity, truth_activity, agent_to_truth)
    if activity_score <= 0:
        return None
    weight = _NODE_MATCH_CARDINALITY_BONUS
    weight += 3.0 * topology_similarity
    weight += _NODE_MATCH_ACTIVITY_WEIGHT * activity_score
    for property_name, property_weight in _NODE_MATCH_ATTRIBUTE_WEIGHTS.items():
        if property_name in ("reads", "writes"):
            score, _ = score_list_slot(
                agent_node.slot_value(property_name),
                truth_node.slot_value(property_name),
                agent_to_truth,
            )
        else:
            score = score_scalar_slot(
                agent_node.slot_value(property_name),
                truth_node.slot_value(property_name),
                agent_to_truth,
            )
        weight += property_weight * score
    return weight


def _map_nodes_one_to_one(
    agent: AgentGraph,
    truth: BusinessGraphView,
    agent_to_truth: dict[str, str],
) -> dict[str, str]:
    """Map Nodes using activity identity, attributes, and soft topology."""
    agent_fingerprints, truth_fingerprints = _topology_fingerprints(agent, truth)
    weights: dict[tuple[str, str], float] = {}
    for agent_node_id, agent_fingerprint in agent_fingerprints.items():
        for truth_node_id, truth_fingerprint in truth_fingerprints.items():
            weight = _node_attribute_weight(
                agent.nodes[agent_node_id],
                truth.nodes[truth_node_id],
                agent_to_truth,
                _topology_similarity(agent_fingerprint, truth_fingerprint),
            )
            if weight is not None:
                weights[(agent_node_id, truth_node_id)] = weight

    mapping: dict[str, str] = {}
    for left, right in bipartite_components(weights):
        if max(len(left), len(right)) > _NODE_AMBIGUITY_CLASS_LIMIT:
            continue
        component_weights = {
            pair: weight
            for pair, weight in weights.items()
            if pair[0] in left and pair[1] in right
        }
        assignment = max_weight_assignment(
            component_weights,
            left,
            right,
            threshold=0.0,
        )
        if not assignment:
            continue
        optimum = assignment_score(assignment, component_weights)
        for agent_node_id, truth_node_id in assignment.items():
            alternative_weights = {
                pair: weight
                for pair, weight in component_weights.items()
                if pair != (agent_node_id, truth_node_id)
            }
            alternative = max_weight_assignment(
                alternative_weights,
                left,
                right,
                threshold=0.0,
            )
            if math.isclose(
                assignment_score(alternative, component_weights),
                optimum,
                rel_tol=1e-12,
                abs_tol=1e-9,
            ):
                continue
            mapping[agent_node_id] = truth_node_id
    return mapping


def _map_edges_one_to_one(
    agent: AgentGraph,
    truth: BusinessGraphView,
    node_mapping: dict[str, str],
    agent_to_truth: dict[str, str],
) -> dict[str, str]:
    """Map business Edges after Node mapping using endpoints then conditions."""
    agent_by_endpoints: dict[tuple[str, str], list[str]] = {}
    for edge_id in business_edge_ids(agent):
        edge = agent.edges[edge_id]
        from_node = node_mapping.get(edge.from_node)
        to_node = node_mapping.get(edge.to_node)
        if from_node is None or to_node is None:
            continue
        agent_by_endpoints.setdefault((from_node, to_node), []).append(edge_id)

    truth_by_endpoints: dict[tuple[str, str], list[str]] = {}
    for edge_id in business_edge_ids(truth):
        edge = truth.edges[edge_id]
        truth_by_endpoints.setdefault((edge.from_node, edge.to_node), []).append(
            edge_id
        )

    edge_mapping: dict[str, str] = {}
    for endpoint_pair in sorted(agent_by_endpoints):
        agent_edge_ids = sorted(agent_by_endpoints[endpoint_pair])
        truth_edge_ids = sorted(truth_by_endpoints.get(endpoint_pair, ()))
        if not truth_edge_ids:
            continue
        weights: dict[tuple[str, str], float] = {}
        for agent_edge_id in agent_edge_ids:
            for truth_edge_id in truth_edge_ids:
                condition_score = score_scalar_slot(
                    agent.edges[agent_edge_id].condition,
                    truth.edges[truth_edge_id].condition,
                    agent_to_truth,
                )
                weights[(agent_edge_id, truth_edge_id)] = (
                    _EDGE_CARDINALITY_WEIGHT + condition_score
                )
        edge_mapping.update(
            max_weight_assignment(
                weights,
                agent_edge_ids,
                truth_edge_ids,
                threshold=0.0,
            )
        )
    return edge_mapping


def align_agent_to_truth(
    agent: AgentGraph,
    truth: BusinessProcessGraph | BusinessGraphView,
    terminology_terms: dict[str, list[str]] | None = None,
) -> GraphAlignment:
    """Align concepts, then Nodes, then business Edges deterministically."""
    truth_view = business_graph_projection(truth)
    concept_alignment: ConceptAlignment = align_concepts(
        agent, truth_view, terminology_terms
    )
    node_mapping = _map_nodes_one_to_one(
        agent, truth_view, concept_alignment.concept_to_truth
    )
    edge_mapping = _map_edges_one_to_one(
        agent, truth_view, node_mapping, concept_alignment.concept_to_truth
    )
    return GraphAlignment(
        concept_to_truth=concept_alignment.concept_to_truth,
        node_to_truth=node_mapping,
        edge_to_truth=edge_mapping,
        concept_recall=concept_alignment.concept_recall,
        concept_precision=concept_alignment.concept_precision,
    )


__all__ = ["GraphAlignment", "align_agent_to_truth"]
