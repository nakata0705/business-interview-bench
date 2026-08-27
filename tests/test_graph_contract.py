"""Focused canonical-contract tests derived from the tau2 oracle."""

from __future__ import annotations

import pytest

from business_interview.models import (  # pyright: ignore[reportMissingImports]
    STRUCTURAL_BOUNDARY_EDGE_PREFIX,
    STRUCTURAL_SINK_ID,
    STRUCTURAL_SOURCE_ID,
    BusinessProcessGraph,
    ConceptRef,
    TruthConcept,
    TruthEdge,
    TruthNode,
    business_edge_ids,
    business_entry_node_ids,
    business_exit_node_ids,
    business_node_ids,
    canonical_structure_errors,
    canonicalize_truth_graph,
    validate_canonical_graph,
)


def _raw_graph(
    node_ids: tuple[str, ...], edge_pairs: tuple[tuple[str, str], ...]
) -> BusinessProcessGraph:
    concepts = {
        f"activity_{node_id}": TruthConcept(
            id=f"activity_{node_id}",
            kind="activity",
            canonical_terms=[f"activity {node_id}"],
        )
        for node_id in node_ids
    }
    nodes = {
        node_id: TruthNode(
            id=node_id,
            activity=ConceptRef(concept_id=f"activity_{node_id}"),
        )
        for node_id in node_ids
    }
    edges = {
        f"edge_{index}": TruthEdge(id=f"edge_{index}", from_node=source, to_node=target)
        for index, (source, target) in enumerate(edge_pairs, start=1)
    }
    return BusinessProcessGraph(
        id="fixture",
        name="Contract fixture",
        nodes=nodes,
        edges=edges,
        concepts=concepts,
    )


def _linear() -> BusinessProcessGraph:
    return canonicalize_truth_graph(
        _raw_graph(("a", "b"), (("a", "b"),)),
        entry_node_ids=["a"],
        exit_node_ids=["b"],
    )


def test_valid_linear_graph_has_explicit_protected_boundaries() -> None:
    graph = _linear()

    assert canonical_structure_errors(graph) == []
    validate_canonical_graph(graph)
    assert graph.nodes[STRUCTURAL_SOURCE_ID].protected
    assert graph.nodes[STRUCTURAL_SINK_ID].protected
    assert business_node_ids(graph) == ["a", "b"]
    assert business_edge_ids(graph) == ["edge_1"]
    assert business_entry_node_ids(graph) == ("a",)
    assert business_exit_node_ids(graph) == ("b",)


def test_multiple_business_entries_and_exits_are_supported() -> None:
    entries = canonicalize_truth_graph(
        _raw_graph(("a", "b", "c"), (("a", "c"), ("b", "c")))
    )
    exits = canonicalize_truth_graph(
        _raw_graph(("a", "b", "c"), (("a", "b"), ("a", "c")))
    )

    assert business_entry_node_ids(entries) == ("a", "b")
    assert business_exit_node_ids(entries) == ("c",)
    assert business_entry_node_ids(exits) == ("a",)
    assert business_exit_node_ids(exits) == ("b", "c")
    assert set(entries.successors(STRUCTURAL_SOURCE_ID)) == {"a", "b"}
    assert set(exits.successors("a")) == {"b", "c"}


def test_disconnected_business_node_is_rejected() -> None:
    graph = _linear()
    graph.nodes["orphan"] = TruthNode(
        id="orphan", activity=ConceptRef(concept_id="activity_a")
    )

    errors = canonical_structure_errors(graph)

    assert any("isolated business nodes" in error for error in errors)
    with pytest.raises(ValueError, match="canonical graph"):
        validate_canonical_graph(graph)


def test_extra_topology_source_is_rejected() -> None:
    graph = _linear()
    source_edge_id = next(
        edge_id
        for edge_id, edge in graph.edges.items()
        if edge.from_node == STRUCTURAL_SOURCE_ID
    )
    graph.edges.pop(source_edge_id)

    errors = canonical_structure_errors(graph)

    assert any("topology sources" in error for error in errors)


def test_extra_topology_sink_is_rejected() -> None:
    graph = _linear()
    sink_edge_id = next(
        edge_id
        for edge_id, edge in graph.edges.items()
        if edge.to_node == STRUCTURAL_SINK_ID
    )
    graph.edges.pop(sink_edge_id)

    errors = canonical_structure_errors(graph)

    assert any("topology sinks" in error for error in errors)


def test_dangling_edge_is_rejected() -> None:
    graph = _linear()
    graph.edges["dangling"] = TruthEdge(id="dangling", from_node="a", to_node="missing")

    errors = canonical_structure_errors(graph)

    assert any("dangling edges" in error for error in errors)


def test_structural_node_cannot_carry_business_semantics() -> None:
    graph = _linear()
    graph.nodes[STRUCTURAL_SOURCE_ID].activity = ConceptRef(concept_id="activity_a")

    errors = canonical_structure_errors(graph)

    assert any("structural node" in error and "activity" in error for error in errors)


def test_structural_boundary_must_be_unconditional() -> None:
    graph = _linear()
    boundary = next(
        edge for edge in graph.edges.values() if edge.from_node == STRUCTURAL_SOURCE_ID
    )
    boundary.condition = ConceptRef(concept_id="activity_a")

    errors = canonical_structure_errors(graph)

    assert any("must be unconditional" in error for error in errors)


def test_non_structural_edge_cannot_touch_source_or_sink() -> None:
    graph = _linear()
    graph.edges["bad_boundary"] = TruthEdge(
        id="bad_boundary",
        from_node=STRUCTURAL_SOURCE_ID,
        to_node="b",
    )

    errors = canonical_structure_errors(graph)

    assert any("non-structural edge touches SOURCE/SINK" in error for error in errors)


def test_canonicalization_is_insertion_order_invariant() -> None:
    first = _raw_graph(("a", "b", "c"), (("a", "b"), ("b", "c")))
    second = first.model_copy(deep=True)
    second.nodes = dict(reversed(list(second.nodes.items())))
    second.edges = dict(reversed(list(second.edges.items())))
    second.concepts = dict(reversed(list(second.concepts.items())))

    first_canonical = canonicalize_truth_graph(first)
    second_canonical = canonicalize_truth_graph(second)

    assert first_canonical == second_canonical
    assert first_canonical.model_dump_json() == second_canonical.model_dump_json()


def test_reserved_structural_ids_are_rejected() -> None:
    node_collision = _raw_graph(
        (STRUCTURAL_SOURCE_ID, "b"), ((STRUCTURAL_SOURCE_ID, "b"),)
    )
    edge_collision = _raw_graph(("a", "b"), (("a", "b"),))
    edge_collision.edges["edge_1"].id = f"{STRUCTURAL_BOUNDARY_EDGE_PREFIX}collision"
    edge_collision.edges = {
        f"{STRUCTURAL_BOUNDARY_EDGE_PREFIX}collision": edge_collision.edges.pop(
            "edge_1"
        )
    }

    with pytest.raises(ValueError, match="reserved structural node id"):
        canonicalize_truth_graph(node_collision)
    with pytest.raises(ValueError, match="reserved structural edge id"):
        canonicalize_truth_graph(edge_collision)


def test_existing_canonical_graph_is_validated_not_repaired_silently() -> None:
    graph = _linear()
    graph.nodes[STRUCTURAL_SOURCE_ID].protected = False

    with pytest.raises(ValueError, match="protected"):
        canonicalize_truth_graph(graph)
