"""Tests for the tau2-free deterministic comparison core."""

# The project-level uv Pyright configuration resolves the target package;
# this directive quiets the workspace-level auxiliary resolver.
# pyright: reportMissingImports=false

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from business_interview.comparison import (
    align_agent_to_truth,
    business_graph_projection,
    compare_aligned_graphs,
    concept_similarity,
    dice_similarity,
    normalize_text,
    score_list_slot,
    score_scalar_slot,
    tokenize,
)
from business_interview.models import (
    ABSENT,
    DONT_KNOW,
    UNSET,
    AgentConcept,
    AgentEdge,
    AgentGraph,
    AgentNode,
    BusinessProcessGraph,
    ConceptRef,
    TruthConcept,
    TruthEdge,
    TruthNode,
    canonicalize_truth_graph,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = PROJECT_ROOT / "src" / "business_interview" / "replay_data" / "seed9004"
PHASE4_FIELDS = (
    "graph_created",
    "graph_valid",
    "node_recall",
    "node_precision",
    "edge_recall",
    "edge_precision",
    "start_correct",
    "end_recall",
    "end_precision",
    "activity_correctness",
    "actor_correctness",
    "system_correctness",
    "read_correctness",
    "write_correctness",
    "rationale_correctness",
    "condition_correctness",
    "concept_correctness",
    "concept_recall",
    "concept_precision",
    "unsupported_ref_count",
    "fabricated_node_count",
    "fabricated_edge_count",
    "glossary_complete",
)


def _ref(concept_id: str) -> ConceptRef:
    return ConceptRef(concept_id=concept_id)


def _truth(
    concepts: dict[str, TruthConcept],
    nodes: dict[str, TruthNode],
    edges: dict[str, TruthEdge] | None = None,
    *,
    entries: list[str] | None = None,
    exits: list[str] | None = None,
) -> BusinessProcessGraph:
    graph = BusinessProcessGraph(
        id="test_truth",
        concepts=concepts,
        nodes=nodes,
        edges=edges or {},
    )
    return canonicalize_truth_graph(
        graph,
        entry_node_ids=entries or list(nodes),
        exit_node_ids=exits or list(nodes),
    )


def _agent(
    concepts: dict[str, AgentConcept],
    nodes: dict[str, AgentNode],
    edges: dict[str, Any] | None = None,
    *,
    starts: list[str] | None = None,
    ends: list[str] | None = None,
) -> AgentGraph:
    return AgentGraph(
        id="test_agent",
        concepts=concepts,
        nodes=nodes,
        edges=edges or {},
        start_node_ids=starts or list(nodes),
        end_node_ids=ends or list(nodes),
    )


def _fixture_graphs() -> tuple[BusinessProcessGraph, AgentGraph, dict[str, Any]]:
    truth = BusinessProcessGraph.model_validate_json(
        (FIXTURE_ROOT / "truth.json").read_text(encoding="utf-8")
    )
    agent = AgentGraph.model_validate_json(
        (FIXTURE_ROOT / "agent.json").read_text(encoding="utf-8")
    )
    expected = json.loads((FIXTURE_ROOT / "expected.json").read_text(encoding="utf-8"))
    return truth, agent, expected


def _rename_slot(value: Any, concept_ids: dict[str, str]) -> Any:
    if isinstance(value, ConceptRef):
        return value.model_copy(update={"concept_id": concept_ids[value.concept_id]})
    if isinstance(value, list):
        return [_rename_slot(item, concept_ids) for item in value]
    return value


def _rename_agent_concepts(agent: AgentGraph) -> AgentGraph:
    concept_ids = {
        concept_id: f"renamed_{index:03d}"
        for index, concept_id in enumerate(sorted(agent.concepts), start=1)
    }
    renamed = agent.model_copy(deep=True)
    renamed.concepts = {
        concept_ids[concept_id]: concept.model_copy(
            update={"id": concept_ids[concept_id]}
        )
        for concept_id, concept in agent.concepts.items()
    }
    for node_id, node in renamed.nodes.items():
        renamed.nodes[node_id] = node.model_copy(
            update={
                "activity": _rename_slot(node.activity, concept_ids),
                "actor": _rename_slot(node.actor, concept_ids),
                "system": _rename_slot(node.system, concept_ids),
                "reads": _rename_slot(node.reads, concept_ids),
                "writes": _rename_slot(node.writes, concept_ids),
                "necessity_rationale": _rename_slot(
                    node.necessity_rationale, concept_ids
                ),
            }
        )
    for edge_id, edge in renamed.edges.items():
        renamed.edges[edge_id] = edge.model_copy(
            update={"condition": _rename_slot(edge.condition, concept_ids)}
        )
    return renamed


def _comparison(truth: BusinessProcessGraph, agent: AgentGraph) -> Any:
    alignment = align_agent_to_truth(agent, truth)
    return compare_aligned_graphs(agent, truth, alignment)


def test_seed9004_graph_content_parity_is_exact() -> None:
    truth, agent, expected = _fixture_graphs()
    alignment = align_agent_to_truth(agent, truth)
    comparison = compare_aligned_graphs(agent, truth, alignment)

    assert {field: getattr(comparison, field) for field in PHASE4_FIELDS} == {
        field: expected["oracle"]["fields"][field] for field in PHASE4_FIELDS
    }
    assert alignment.node_to_truth == {
        "node_approve_high_value": "ap",
        "node_check_customer_info": "cc",
        "node_create_quotation": "cq",
        "node_receive_request": "r",
        "node_send_month_end_summary": "me",
        "node_send_quotation_customer": "sq",
    }
    assert alignment.edge_to_truth == {
        "edge_approve_to_send_customer": "e5",
        "edge_check_to_create": "e2",
        "edge_create_to_approve": "e3",
        "edge_create_to_month_end": "e6",
        "edge_create_to_send_customer": "e4",
        "edge_receive_to_check": "e1",
    }


def test_business_projection_excludes_structural_elements() -> None:
    truth, _, _ = _fixture_graphs()
    projected = business_graph_projection(truth)

    assert set(projected.nodes) == {"ap", "cc", "cq", "me", "r", "sq"}
    assert set(projected.edges) == {"e1", "e2", "e3", "e4", "e5", "e6"}
    assert projected.start_node_ids == ("r",)
    assert projected.end_node_ids == ("me", "sq")
    assert truth.source_node_id in truth.nodes
    assert truth.sink_node_id in truth.nodes


def test_lexical_normalization_dice_and_cjk_signatures() -> None:
    assert normalize_text(" ＣＲＭ ") == " crm "
    assert tokenize("the customer information") == {"customer"}
    assert tokenize("顧客情報") == {"顧客", "客情", "情報"}
    assert dice_similarity({"customer", "info"}, {"customer", "data"}) == 0.5
    assert (
        concept_similarity(
            AgentConcept(id="a", kind="system", display_label="ＣＲＭ"),
            TruthConcept(id="t", kind="system", canonical_terms=["CRM"]),
        )
        == 1.0
    )


def test_exact_label_does_not_make_unrelated_generic_label_match() -> None:
    agent = AgentConcept(id="a", kind="system", display_label="system")
    specific_truth = TruthConcept(
        id="t_specific", kind="system", canonical_terms=["payment system"]
    )
    generic_truth = TruthConcept(
        id="t_generic", kind="system", canonical_terms=["system"]
    )

    assert concept_similarity(agent, specific_truth) == 0.0
    assert concept_similarity(agent, generic_truth) == 1.0


def test_concept_alignment_is_one_to_one() -> None:
    truth = _truth(
        {
            "t_one": TruthConcept(
                id="t_one", kind="activity", canonical_terms=["alpha process"]
            ),
            "t_two": TruthConcept(
                id="t_two", kind="activity", canonical_terms=["beta process"]
            ),
        },
        {
            "n_one": TruthNode(id="n_one", activity=_ref("t_one")),
            "n_two": TruthNode(id="n_two", activity=_ref("t_two")),
        },
    )
    agent = _agent(
        {
            "a_one": AgentConcept(
                id="a_one", kind="activity", display_label="alpha process"
            ),
            "a_two": AgentConcept(
                id="a_two", kind="activity", display_label="beta process"
            ),
        },
        {
            "m_one": AgentNode(id="m_one", activity=_ref("a_one")),
            "m_two": AgentNode(id="m_two", activity=_ref("a_two")),
        },
    )

    mapping = align_agent_to_truth(agent, truth).concept_to_truth
    assert mapping == {"a_one": "t_one", "a_two": "t_two"}
    assert len(set(mapping.values())) == len(mapping)


def test_agent_concept_id_rename_does_not_change_alignment_or_scores() -> None:
    truth, agent, _ = _fixture_graphs()
    renamed = _rename_agent_concepts(agent)

    original_alignment = align_agent_to_truth(agent, truth)
    renamed_alignment = align_agent_to_truth(renamed, truth)
    original_result = compare_aligned_graphs(agent, truth, original_alignment)
    renamed_result = compare_aligned_graphs(renamed, truth, renamed_alignment)

    assert original_alignment.node_to_truth == renamed_alignment.node_to_truth
    assert original_alignment.edge_to_truth == renamed_alignment.edge_to_truth
    assert set(original_alignment.concept_to_truth.values()) == set(
        renamed_alignment.concept_to_truth.values()
    )
    assert asdict(original_result) == asdict(renamed_result)


def test_insertion_order_does_not_change_alignment_or_scores() -> None:
    truth, agent, _ = _fixture_graphs()
    reordered_truth = truth.model_copy(deep=True)
    reordered_truth.concepts = dict(reversed(list(reordered_truth.concepts.items())))
    reordered_truth.nodes = dict(reversed(list(reordered_truth.nodes.items())))
    reordered_truth.edges = dict(reversed(list(reordered_truth.edges.items())))
    reordered_agent = agent.model_copy(deep=True)
    reordered_agent.concepts = dict(reversed(list(reordered_agent.concepts.items())))
    reordered_agent.nodes = dict(reversed(list(reordered_agent.nodes.items())))
    reordered_agent.edges = dict(reversed(list(reordered_agent.edges.items())))

    assert asdict(_comparison(truth, agent)) == asdict(
        _comparison(reordered_truth, reordered_agent)
    )


def test_symmetric_duplicate_nodes_are_left_unmatched() -> None:
    concepts = {
        "activity": TruthConcept(
            id="activity", kind="activity", canonical_terms=["same activity"]
        )
    }
    truth = _truth(
        concepts,
        {
            "truth_a": TruthNode(id="truth_a", activity=_ref("activity")),
            "truth_b": TruthNode(id="truth_b", activity=_ref("activity")),
        },
        entries=["truth_a", "truth_b"],
        exits=["truth_a", "truth_b"],
    )
    agent = _agent(
        {
            "activity": AgentConcept(
                id="activity", kind="activity", display_label="same activity"
            )
        },
        {
            "agent_a": AgentNode(id="agent_a", activity=_ref("activity")),
            "agent_b": AgentNode(id="agent_b", activity=_ref("activity")),
        },
        starts=["agent_a", "agent_b"],
        ends=["agent_a", "agent_b"],
    )

    alignment = align_agent_to_truth(agent, truth)
    assert alignment.node_to_truth == {}
    assert alignment.edge_to_truth == {}


def test_topology_mismatch_does_not_reject_activity_candidate() -> None:
    truth = _truth(
        {
            "first": TruthConcept(
                id="first", kind="activity", canonical_terms=["first step"]
            ),
            "second": TruthConcept(
                id="second", kind="activity", canonical_terms=["second step"]
            ),
        },
        {
            "truth_first": TruthNode(id="truth_first", activity=_ref("first")),
            "truth_second": TruthNode(id="truth_second", activity=_ref("second")),
        },
        {"step": TruthEdge(id="step", from_node="truth_first", to_node="truth_second")},
        entries=["truth_first"],
        exits=["truth_second"],
    )
    agent = _agent(
        {
            "first": AgentConcept(
                id="first", kind="activity", display_label="first step"
            )
        },
        {"agent_first": AgentNode(id="agent_first", activity=_ref("first"))},
    )

    alignment = align_agent_to_truth(agent, truth)
    assert alignment.node_to_truth == {"agent_first": "truth_first"}


def test_parallel_edges_are_matched_one_to_one_by_condition() -> None:
    truth = _truth(
        {
            "first": TruthConcept(
                id="first", kind="activity", canonical_terms=["first"]
            ),
            "second": TruthConcept(
                id="second", kind="activity", canonical_terms=["second"]
            ),
            "urgent": TruthConcept(
                id="urgent", kind="condition", canonical_terms=["urgent"]
            ),
            "routine": TruthConcept(
                id="routine", kind="condition", canonical_terms=["routine"]
            ),
        },
        {
            "truth_first": TruthNode(id="truth_first", activity=_ref("first")),
            "truth_second": TruthNode(id="truth_second", activity=_ref("second")),
        },
        {
            "truth_routine": TruthEdge(
                id="truth_routine",
                from_node="truth_first",
                to_node="truth_second",
                condition=_ref("routine"),
            ),
            "truth_urgent": TruthEdge(
                id="truth_urgent",
                from_node="truth_first",
                to_node="truth_second",
                condition=_ref("urgent"),
            ),
        },
        entries=["truth_first"],
        exits=["truth_second"],
    )
    agent = _agent(
        {
            "first": AgentConcept(id="first", kind="activity", display_label="first"),
            "second": AgentConcept(
                id="second", kind="activity", display_label="second"
            ),
            "urgent": AgentConcept(
                id="urgent", kind="condition", display_label="urgent"
            ),
            "routine": AgentConcept(
                id="routine", kind="condition", display_label="routine"
            ),
        },
        {
            "agent_first": AgentNode(id="agent_first", activity=_ref("first")),
            "agent_second": AgentNode(id="agent_second", activity=_ref("second")),
        },
        {
            "agent_urgent": AgentEdge(
                id="agent_urgent",
                from_node="agent_first",
                to_node="agent_second",
                condition=_ref("urgent"),
            ),
            "agent_routine": AgentEdge(
                id="agent_routine",
                from_node="agent_first",
                to_node="agent_second",
                condition=_ref("routine"),
            ),
        },
        starts=["agent_first"],
        ends=["agent_second"],
    )

    alignment = align_agent_to_truth(agent, truth)
    comparison = compare_aligned_graphs(agent, truth, alignment)
    assert len(alignment.edge_to_truth) == 2
    assert set(alignment.edge_to_truth.values()) == {
        "truth_routine",
        "truth_urgent",
    }
    assert comparison.condition_correctness == 1.0


def test_truth_absence_requires_absent_not_unset_or_dont_know() -> None:
    truth_value = None
    assert score_scalar_slot(ABSENT, truth_value, {}) == 1
    assert score_scalar_slot(UNSET, truth_value, {}) == 0
    assert score_scalar_slot(DONT_KNOW, truth_value, {}) == 0


def test_unset_activity_makes_comparison_graph_invalid_like_source() -> None:
    truth = _truth(
        {
            "activity": TruthConcept(
                id="activity", kind="activity", canonical_terms=["inspect"]
            )
        },
        {"truth_node": TruthNode(id="truth_node", activity=_ref("activity"))},
        entries=["truth_node"],
        exits=["truth_node"],
    )
    agent = _agent(
        {},
        {"agent_node": AgentNode(id="agent_node", activity=UNSET)},
        starts=["agent_node"],
        ends=["agent_node"],
    )

    assert _comparison(truth, agent).graph_valid is False


def test_reads_and_writes_count_unsupported_asserted_references() -> None:
    truth = _truth(
        {
            "activity": TruthConcept(
                id="activity", kind="activity", canonical_terms=["inspect"]
            ),
            "known_data": TruthConcept(
                id="known_data", kind="data", canonical_terms=["customer record"]
            ),
        },
        {
            "truth_node": TruthNode(
                id="truth_node",
                activity=_ref("activity"),
                reads=[_ref("known_data")],
            )
        },
        entries=["truth_node"],
        exits=["truth_node"],
    )
    agent = _agent(
        {
            "activity": AgentConcept(
                id="activity", kind="activity", display_label="inspect"
            ),
            "known_data": AgentConcept(
                id="known_data", kind="data", display_label="customer record"
            ),
            "unknown_data": AgentConcept(
                id="unknown_data", kind="data", display_label="unrelated artifact"
            ),
        },
        {
            "agent_node": AgentNode(
                id="agent_node",
                activity=_ref("activity"),
                reads=[_ref("known_data"), _ref("unknown_data")],
                writes=ABSENT,
            )
        },
        starts=["agent_node"],
        ends=["agent_node"],
    )

    comparison = _comparison(truth, agent)
    assert comparison.read_correctness == 1.0
    assert comparison.unsupported_ref_count == 1
    assert score_list_slot(
        [_ref("unknown_data")],
        [_ref("known_data")],
        {"known_data": "known_data"},
    ) == (0.0, 0)
