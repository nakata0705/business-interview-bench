"""Canonical SOURCE/SINK contract for Truth graphs."""

from __future__ import annotations

from collections import deque
from typing import Any

from .graph import (
    STRUCTURAL_BOUNDARY_EDGE_PREFIX,
    STRUCTURAL_SINK_ID,
    STRUCTURAL_SOURCE_ID,
    BusinessProcessGraph,
    TruthEdge,
    TruthNode,
)


def node_is_structural(node: Any) -> bool:
    """Return whether a node has explicit structural metadata."""
    return bool(
        getattr(node, "structural", False)
        or getattr(node, "structural_role", None) is not None
    )


def edge_is_structural(edge: Any) -> bool:
    """Return whether an edge is a structural-only boundary edge."""
    return bool(
        getattr(edge, "structural_only", False)
        or getattr(edge, "edge_kind", None) == "structural_boundary"
    )


def business_node_ids(graph: Any) -> list[str]:
    """Return sorted non-structural node IDs."""
    return sorted(
        node_id
        for node_id, node in getattr(graph, "nodes", {}).items()
        if not node_is_structural(node)
    )


def business_edge_ids(graph: Any) -> list[str]:
    """Return sorted non-structural edge IDs."""
    return sorted(
        edge_id
        for edge_id, edge in getattr(graph, "edges", {}).items()
        if not edge_is_structural(edge)
    )


def business_entry_node_ids(graph: Any) -> tuple[str, ...]:
    """Return business nodes directly reached from the structural SOURCE."""
    source_id = getattr(graph, "source_node_id", None)
    business = set(business_node_ids(graph))
    return tuple(
        sorted(
            {
                edge.to_node
                for edge in getattr(graph, "edges", {}).values()
                if edge.from_node == source_id and edge.to_node in business
            }
        )
    )


def business_exit_node_ids(graph: Any) -> tuple[str, ...]:
    """Return business nodes directly feeding the structural SINK."""
    sink_id = getattr(graph, "sink_node_id", None)
    business = set(business_node_ids(graph))
    return tuple(
        sorted(
            {
                edge.from_node
                for edge in getattr(graph, "edges", {}).values()
                if edge.to_node == sink_id and edge.from_node in business
            }
        )
    )


def _adjacency(
    graph: Any,
) -> tuple[dict[str, set[str]], dict[str, set[str]], list[str]]:
    nodes = set(getattr(graph, "nodes", {}))
    forward = {node_id: set() for node_id in nodes}
    reverse = {node_id: set() for node_id in nodes}
    dangling: list[str] = []
    for edge_id, edge in getattr(graph, "edges", {}).items():
        if edge.from_node not in nodes or edge.to_node not in nodes:
            dangling.append(edge_id)
            continue
        forward[edge.from_node].add(edge.to_node)
        reverse[edge.to_node].add(edge.from_node)
    return forward, reverse, sorted(dangling)


def _reachable(starts: set[str], adjacency: dict[str, set[str]]) -> set[str]:
    reached = set(starts)
    queue = deque(sorted(reached))
    while queue:
        node_id = queue.popleft()
        for successor in sorted(adjacency.get(node_id, ())):
            if successor not in reached:
                reached.add(successor)
                queue.append(successor)
    return reached


def _structural_property_is_empty(value: object) -> bool:
    return value is None or value == [] or value == ()


def canonical_structure_errors(graph: Any) -> list[str]:
    """Return all violations of the explicit single SOURCE/SINK contract."""
    nodes = getattr(graph, "nodes", {})
    edges = getattr(graph, "edges", {})
    source_id = getattr(graph, "source_node_id", None)
    sink_id = getattr(graph, "sink_node_id", None)
    errors: list[str] = []

    if not nodes:
        return ["canonical graph must contain at least one business node"]
    if source_id is None or sink_id is None:
        return ["canonical graph must declare source_node_id and sink_node_id"]
    if source_id == sink_id:
        errors.append("SOURCE and SINK must be distinct")

    source_roles = sorted(
        node_id
        for node_id, node in nodes.items()
        if getattr(node, "structural_role", None) == "source"
    )
    sink_roles = sorted(
        node_id
        for node_id, node in nodes.items()
        if getattr(node, "structural_role", None) == "sink"
    )
    if source_roles != [source_id]:
        errors.append(
            f"expected exactly one structural SOURCE {source_id!r}; "
            f"found role nodes {source_roles!r}"
        )
    if sink_roles != [sink_id]:
        errors.append(
            f"expected exactly one structural SINK {sink_id!r}; "
            f"found role nodes {sink_roles!r}"
        )
    if source_id not in nodes:
        errors.append(f"structural SOURCE node not found: {source_id}")
    if sink_id not in nodes:
        errors.append(f"structural SINK node not found: {sink_id}")

    for node_id, node in nodes.items():
        if node_is_structural(node):
            if node_id not in {source_id, sink_id}:
                errors.append(f"unexpected structural node: {node_id}")
            if not getattr(node, "protected", False):
                errors.append(f"structural node is not protected: {node_id}")
            for property_name in (
                "activity",
                "actor",
                "system",
                "reads",
                "writes",
                "necessity_rationale",
            ):
                if not _structural_property_is_empty(
                    getattr(node, property_name, None)
                ):
                    errors.append(
                        f"structural node {node_id}: semantic property "
                        f"{property_name} is set"
                    )
        elif getattr(node, "structural_role", None) is not None:
            errors.append(f"business node {node_id} has a structural role")

    forward, reverse, dangling = _adjacency(graph)
    if dangling:
        errors.append(f"dangling edges: {dangling!r}")

    topology_sources = sorted(
        node_id for node_id in nodes if len(reverse.get(node_id, set())) == 0
    )
    topology_sinks = sorted(
        node_id for node_id in nodes if len(forward.get(node_id, set())) == 0
    )
    if topology_sources != [source_id]:
        errors.append(
            f"topology sources must be exactly [SOURCE]; found {topology_sources!r}"
        )
    if topology_sinks != [sink_id]:
        errors.append(
            f"topology sinks must be exactly [SINK]; found {topology_sinks!r}"
        )
    if source_id in reverse and reverse[source_id]:
        errors.append("SOURCE must have indegree 0")
    if sink_id in forward and forward[sink_id]:
        errors.append("SINK must have outdegree 0")

    business = set(nodes) - {source_id, sink_id}
    if not business:
        errors.append("canonical graph must contain at least one business node")
    reachable_from_source = _reachable(
        {source_id} if source_id in nodes else set(), forward
    )
    can_reach_sink = _reachable({sink_id} if sink_id in nodes else set(), reverse)
    missing_source = sorted(business - reachable_from_source)
    missing_sink = sorted(business - can_reach_sink)
    if missing_source:
        errors.append(f"business nodes not SOURCE-reachable: {missing_source!r}")
    if missing_sink:
        errors.append(f"business nodes cannot reach SINK: {missing_sink!r}")
    isolated = sorted(
        node_id
        for node_id in business
        if not forward.get(node_id) and not reverse.get(node_id)
    )
    if isolated:
        errors.append(f"isolated business nodes: {isolated!r}")

    structural_edge_ids: set[str] = set()
    for edge_id, edge in edges.items():
        structural = edge_is_structural(edge)
        if structural:
            structural_edge_ids.add(edge_id)
            if not getattr(edge, "protected", False):
                errors.append(f"structural edge is not protected: {edge_id}")
            if getattr(edge, "condition", None) is not None:
                errors.append(f"structural edge must be unconditional: {edge_id}")
            valid_boundary = (
                edge.from_node == source_id and edge.to_node in business
            ) or (edge.to_node == sink_id and edge.from_node in business)
            if not valid_boundary:
                errors.append(
                    f"structural edge is not a SOURCE/entry or exit/SINK boundary: "
                    f"{edge_id}"
                )
        elif edge.from_node in {source_id, sink_id} or edge.to_node in {
            source_id,
            sink_id,
        }:
            errors.append(f"non-structural edge touches SOURCE/SINK: {edge_id}")

    if source_id in nodes and not any(
        edge_id in structural_edge_ids and edges[edge_id].from_node == source_id
        for edge_id in edges
    ):
        errors.append("SOURCE must have at least one protected boundary edge")
    if sink_id in nodes and not any(
        edge_id in structural_edge_ids and edges[edge_id].to_node == sink_id
        for edge_id in edges
    ):
        errors.append("SINK must have at least one protected boundary edge")
    return errors


def validate_canonical_graph(graph: Any) -> None:
    """Raise ``ValueError`` unless ``graph`` satisfies the contract."""
    errors = canonical_structure_errors(graph)
    if errors:
        raise ValueError("Invalid canonical graph:\n- " + "\n- ".join(errors))


def _boundary_edge_id(side: str, ordinal: int) -> str:
    return f"{STRUCTURAL_BOUNDARY_EDGE_PREFIX}{side}_{ordinal:03d}"


def canonicalize_truth_graph(
    graph: BusinessProcessGraph,
    *,
    entry_node_ids: list[str] | None = None,
    exit_node_ids: list[str] | None = None,
) -> BusinessProcessGraph:
    """Return a deterministic canonical copy with explicit boundaries.

    The function only adds protected, unconditional boundary metadata. It does
    not invent or rewrite business relations. Existing structural metadata is
    validated rather than silently repaired.
    """
    has_structural_metadata = any(
        node_is_structural(node) for node in graph.nodes.values()
    ) or any(edge_is_structural(edge) for edge in graph.edges.values())
    if has_structural_metadata:
        validate_canonical_graph(graph)

    business_nodes = {
        node_id: node
        for node_id, node in graph.nodes.items()
        if not node_is_structural(node)
    }
    business_edges = {
        edge_id: edge
        for edge_id, edge in graph.edges.items()
        if not edge_is_structural(edge)
    }
    node_ids = set(business_nodes)
    if STRUCTURAL_SOURCE_ID in node_ids or STRUCTURAL_SINK_ID in node_ids:
        raise ValueError("business graph uses a reserved structural node id")
    if any(
        edge_id.startswith(STRUCTURAL_BOUNDARY_EDGE_PREFIX)
        for edge_id in business_edges
    ):
        raise ValueError("business graph uses a reserved structural edge id")

    forward = {node_id: set() for node_id in node_ids}
    reverse = {node_id: set() for node_id in node_ids}
    for edge in business_edges.values():
        if edge.from_node in node_ids and edge.to_node in node_ids:
            forward[edge.from_node].add(edge.to_node)
            reverse[edge.to_node].add(edge.from_node)

    if entry_node_ids is None:
        if has_structural_metadata:
            entry_node_ids = list(business_entry_node_ids(graph))
        else:
            entry_node_ids = sorted(
                node_id for node_id in node_ids if not reverse[node_id]
            )
    if exit_node_ids is None:
        if has_structural_metadata:
            exit_node_ids = list(business_exit_node_ids(graph))
        else:
            exit_node_ids = sorted(
                node_id for node_id in node_ids if not forward[node_id]
            )

    entries = sorted(set(entry_node_ids))
    exits = sorted(set(exit_node_ids))
    if not entries or not exits:
        raise ValueError("cannot canonicalize a graph without explicit entries/exits")
    if any(node_id not in node_ids for node_id in [*entries, *exits]):
        raise ValueError("canonical boundary references an unknown business node")

    canonical = graph.model_copy(deep=True)
    canonical.nodes = {
        node_id: canonical.nodes[node_id] for node_id in sorted(business_nodes)
    }
    canonical.edges = {
        edge_id: canonical.edges[edge_id] for edge_id in sorted(business_edges)
    }
    canonical.concepts = {
        concept_id: canonical.concepts[concept_id]
        for concept_id in sorted(canonical.concepts)
    }
    canonical.nodes[STRUCTURAL_SOURCE_ID] = TruthNode(
        id=STRUCTURAL_SOURCE_ID,
        structural=True,
        structural_role="source",
        protected=True,
    )
    canonical.nodes[STRUCTURAL_SINK_ID] = TruthNode(
        id=STRUCTURAL_SINK_ID,
        structural=True,
        structural_role="sink",
        protected=True,
    )
    for ordinal, node_id in enumerate(entries, start=1):
        edge_id = _boundary_edge_id("source", ordinal)
        canonical.edges[edge_id] = TruthEdge(
            id=edge_id,
            from_node=STRUCTURAL_SOURCE_ID,
            to_node=node_id,
            edge_kind="structural_boundary",
            structural_only=True,
            protected=True,
        )
    for ordinal, node_id in enumerate(exits, start=1):
        edge_id = _boundary_edge_id("sink", ordinal)
        canonical.edges[edge_id] = TruthEdge(
            id=edge_id,
            from_node=node_id,
            to_node=STRUCTURAL_SINK_ID,
            edge_kind="structural_boundary",
            structural_only=True,
            protected=True,
        )

    canonical.source_node_id = STRUCTURAL_SOURCE_ID
    canonical.sink_node_id = STRUCTURAL_SINK_ID
    validate_canonical_graph(canonical)
    return canonical
