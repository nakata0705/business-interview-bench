"""Tests for the tau2-free graph evaluation facade."""

# The workspace-level auxiliary Pyright runner can miss freshly added sibling
# modules; project-level ``uv run pyright`` remains the authoritative check.
# pyright: reportMissingImports=false

from __future__ import annotations

import json
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any

from business_interview.evaluation import GraphEvaluation, evaluate_graph
from business_interview.models import (
    ABSENT,
    AbsentType,
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
PHASE5_FIELDS = (
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
    "structural_pass",
    "reconstruction_pass",
    "quality_pass",
)
UNAVAILABLE_FIELDS = (
    "protocol_completed",
    "protocol_pass",
    "node_evidence_coverage",
    "ref_evidence_coverage",
    "edge_evidence_coverage",
    "invalid_evidence_ref_count",
    "ambiguous_evidence_ref_count",
    "marker_evidence_errors_surrogate",
    "invalid_observation_reference_count",
    "authentic_observation_count",
    "invalid_observation_source_count",
    "orphan_observation_count",
    "provenance_authenticity_pass",
    "evidence_pass",
    "knowledge_coverage",
)


def _ref(concept_id: str) -> ConceptRef:
    return ConceptRef(concept_id=concept_id)


def _truth(
    concepts: dict[str, TruthConcept],
    nodes: dict[str, TruthNode],
    edges: dict[str, TruthEdge] | None = None,
    *,
    entries: list[str],
    exits: list[str],
) -> BusinessProcessGraph:
    return canonicalize_truth_graph(
        BusinessProcessGraph(
            id="test_truth",
            concepts=concepts,
            nodes=nodes,
            edges=edges or {},
        ),
        entry_node_ids=entries,
        exit_node_ids=exits,
    )


def _agent_node(
    node_id: str,
    activity: str,
    *,
    actor: ConceptRef | AbsentType = ABSENT,
) -> AgentNode:
    return AgentNode(
        id=node_id,
        activity=_ref(activity),
        actor=actor,
        system=ABSENT,
        reads=ABSENT,
        writes=ABSENT,
        necessity_rationale=ABSENT,
    )


def _agent(
    concepts: dict[str, AgentConcept],
    nodes: dict[str, AgentNode],
    edges: dict[str, AgentEdge] | None = None,
    *,
    starts: list[str],
    ends: list[str],
) -> AgentGraph:
    return AgentGraph(
        id="test_agent",
        concepts=concepts,
        nodes=nodes,
        edges=edges or {},
        start_node_ids=starts,
        end_node_ids=ends,
    )


def _perfect_pair() -> tuple[AgentGraph, BusinessProcessGraph]:
    truth = _truth(
        {
            "activity": TruthConcept(
                id="activity", kind="activity", canonical_terms=["inspect"]
            )
        },
        {"truth_node": TruthNode(id="truth_node", activity=_ref("activity"))},
        {"loop": TruthEdge(id="loop", from_node="truth_node", to_node="truth_node")},
        entries=["truth_node"],
        exits=["truth_node"],
    )
    agent = _agent(
        {
            "activity": AgentConcept(
                id="activity", kind="activity", display_label="inspect"
            )
        },
        {"agent_node": _agent_node("agent_node", "activity")},
        {
            "loop": AgentEdge(
                id="loop",
                from_node="agent_node",
                to_node="agent_node",
                condition=ABSENT,
            )
        },
        starts=["agent_node"],
        ends=["agent_node"],
    )
    return agent, truth


def _two_node_truth() -> BusinessProcessGraph:
    concepts = {
        "first": TruthConcept(
            id="first", kind="activity", canonical_terms=["first step"]
        ),
        "second": TruthConcept(
            id="second", kind="activity", canonical_terms=["second step"]
        ),
    }
    nodes = {
        "first_node": TruthNode(id="first_node", activity=_ref("first")),
        "second_node": TruthNode(id="second_node", activity=_ref("second")),
    }
    edges = {
        "step": TruthEdge(id="step", from_node="first_node", to_node="second_node")
    }
    return _truth(
        concepts,
        nodes,
        edges,
        entries=["first_node"],
        exits=["second_node"],
    )


def _load_fixture() -> tuple[BusinessProcessGraph, AgentGraph, dict[str, Any]]:
    truth = BusinessProcessGraph.model_validate_json(
        (FIXTURE_ROOT / "truth.json").read_text(encoding="utf-8")
    )
    agent = AgentGraph.model_validate_json(
        (FIXTURE_ROOT / "agent.json").read_text(encoding="utf-8")
    )
    expected = json.loads((FIXTURE_ROOT / "expected.json").read_text(encoding="utf-8"))
    return truth, agent, expected


def test_seed9004_evaluator_matches_exactly_26_oracle_fields() -> None:
    truth, agent, expected = _load_fixture()

    actual = asdict(evaluate_graph(agent, truth))
    oracle = expected["oracle"]["fields"]

    assert tuple(field.name for field in fields(GraphEvaluation)) == PHASE5_FIELDS
    assert len(actual) == 26
    assert set(actual) == set(PHASE5_FIELDS)
    assert {field: actual[field] for field in PHASE5_FIELDS} == {
        field: oracle[field] for field in PHASE5_FIELDS
    }
    assert all(field not in actual for field in UNAVAILABLE_FIELDS)


def test_perfect_graph_passes_all_graph_completeness_lanes() -> None:
    agent, truth = _perfect_pair()

    result = evaluate_graph(agent, truth)

    assert result.graph_created
    assert result.graph_valid
    assert result.structural_pass
    assert result.reconstruction_pass
    assert result.quality_pass


def test_invalid_agent_graph_fails_all_graph_completeness_lanes() -> None:
    agent, truth = _perfect_pair()
    invalid_agent = agent.model_copy(deep=True)
    invalid_agent.edges["dangling"] = AgentEdge(
        id="dangling",
        from_node="agent_node",
        to_node="missing_node",
        condition=ABSENT,
    )

    result = evaluate_graph(invalid_agent, truth)

    assert not result.graph_valid
    assert not result.structural_pass
    assert not result.reconstruction_pass
    assert not result.quality_pass


def test_missing_node_fails_reconstruction() -> None:
    truth = _two_node_truth()
    agent = _agent(
        {
            "first": AgentConcept(
                id="first", kind="activity", display_label="first step"
            )
        },
        {"agent_first": _agent_node("agent_first", "first")},
        starts=["agent_first"],
        ends=["agent_first"],
    )

    result = evaluate_graph(agent, truth)

    assert result.node_recall < 1.0
    assert not result.reconstruction_pass


def test_wrong_slot_value_fails_reconstruction() -> None:
    truth = _truth(
        {
            "activity": TruthConcept(
                id="activity", kind="activity", canonical_terms=["inspect"]
            ),
            "actor": TruthConcept(
                id="actor", kind="actor", canonical_terms=["salesperson"]
            ),
        },
        {
            "truth_node": TruthNode(
                id="truth_node", activity=_ref("activity"), actor=_ref("actor")
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
            "wrong_actor": AgentConcept(
                id="wrong_actor", kind="actor", display_label="unrelated person"
            ),
        },
        {
            "agent_node": _agent_node(
                "agent_node", "activity", actor=_ref("wrong_actor")
            )
        },
        starts=["agent_node"],
        ends=["agent_node"],
    )

    result = evaluate_graph(agent, truth)

    assert result.actor_correctness == 0.0
    assert not result.reconstruction_pass


def test_incomplete_concept_precision_and_recall_fail_reconstruction() -> None:
    truth = _two_node_truth()
    agent = _agent(
        {
            "first": AgentConcept(
                id="first", kind="activity", display_label="first step"
            ),
            "extra": AgentConcept(id="extra", kind="activity", display_label="invoice"),
        },
        {
            "agent_first": _agent_node("agent_first", "first"),
            "agent_extra": _agent_node("agent_extra", "extra"),
        },
        starts=["agent_first"],
        ends=["agent_extra"],
    )

    result = evaluate_graph(agent, truth)

    assert result.concept_recall < 1.0
    assert result.concept_precision < 1.0
    assert not result.reconstruction_pass


def test_evaluation_does_not_mutate_agent_or_truth() -> None:
    agent, truth = _perfect_pair()
    agent_before = agent.model_dump(mode="json")
    truth_before = truth.model_dump(mode="json")

    evaluate_graph(agent, truth)

    assert agent.model_dump(mode="json") == agent_before
    assert truth.model_dump(mode="json") == truth_before


def test_terminology_terms_are_forwarded_deterministically() -> None:
    truth = _truth(
        {
            "activity": TruthConcept(
                id="activity", kind="activity", canonical_terms=["canonical activity"]
            )
        },
        {"truth_node": TruthNode(id="truth_node", activity=_ref("activity"))},
        {"loop": TruthEdge(id="loop", from_node="truth_node", to_node="truth_node")},
        entries=["truth_node"],
        exits=["truth_node"],
    )
    agent = _agent(
        {
            "local_activity": AgentConcept(
                id="local_activity", kind="activity", display_label="private alias"
            )
        },
        {"agent_node": _agent_node("agent_node", "local_activity")},
        {
            "loop": AgentEdge(
                id="loop",
                from_node="agent_node",
                to_node="agent_node",
                condition=ABSENT,
            )
        },
        starts=["agent_node"],
        ends=["agent_node"],
    )
    terminology_terms = {"activity": ["private alias"]}

    without_terms = evaluate_graph(agent, truth)
    with_terms = evaluate_graph(agent, truth, terminology_terms=terminology_terms)
    repeated_with_terms = evaluate_graph(
        agent, truth, terminology_terms=terminology_terms
    )

    assert not without_terms.reconstruction_pass
    assert with_terms.reconstruction_pass
    assert with_terms == repeated_with_terms
    assert terminology_terms == {"activity": ["private alias"]}
