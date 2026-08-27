"""JSON round-trip tests for Truth and Agent graph semantics."""

from __future__ import annotations

from business_interview.models import (  # pyright: ignore[reportMissingImports]
    ABSENT,
    DONT_KNOW,
    UNSET,
    AgentConcept,
    AgentEdge,
    AgentGraph,
    AgentNode,
    BusinessProcessGraph,
    ConceptRef,
    EvidenceRef,
    TruthConcept,
    TruthEdge,
    TruthNode,
    canonical_structure_errors,
    canonicalize_truth_graph,
    is_absent,
    is_dont_know,
    is_unset,
    validate_canonical_graph,
)


def _truth_fixture() -> BusinessProcessGraph:
    return BusinessProcessGraph(
        id="serialization_truth",
        name="Serialization fixture",
        concepts={
            "receive": TruthConcept(
                id="receive",
                kind="activity",
                description="Receive a request",
                canonical_terms=["receive request"],
            ),
            "send": TruthConcept(
                id="send",
                kind="activity",
                description="Send a response",
                canonical_terms=["send response"],
            ),
        },
        nodes={
            "start": TruthNode(id="start", activity=ConceptRef(concept_id="receive")),
            "finish": TruthNode(id="finish", activity=ConceptRef(concept_id="send")),
        },
        edges={"step": TruthEdge(id="step", from_node="start", to_node="finish")},
    )


def test_truth_canonicalize_dump_validate_json_round_trip() -> None:
    canonical = canonicalize_truth_graph(_truth_fixture())
    payload = canonical.model_dump_json()
    restored = BusinessProcessGraph.model_validate_json(payload)

    assert restored == canonical
    assert canonical_structure_errors(restored) == []
    validate_canonical_graph(restored)


def test_agent_four_state_slots_survive_json_round_trip() -> None:
    graph = AgentGraph(
        id="serialization_agent",
        concepts={
            "activity": AgentConcept(
                id="activity", kind="activity", display_label="receive request"
            ),
            "data": AgentConcept(id="data", kind="data", display_label="request"),
            "condition": AgentConcept(
                id="condition", kind="condition", display_label="if urgent"
            ),
        },
        nodes={
            "n1": AgentNode(
                id="n1",
                activity=ConceptRef(
                    concept_id="activity",
                    evidence=[EvidenceRef(observation_id="obs_1", quote="request")],
                ),
                actor=ABSENT,
                system=DONT_KNOW,
                reads=UNSET,
                writes=[ConceptRef(concept_id="data")],
            ),
            "n2": AgentNode(
                id="n2",
                activity=UNSET,
                actor=ConceptRef(concept_id="activity"),
                system=ABSENT,
                reads=DONT_KNOW,
                writes=ABSENT,
            ),
        },
        edges={
            "flow": AgentEdge(
                id="flow",
                from_node="n1",
                to_node="n2",
                condition=DONT_KNOW,
            )
        },
        start_node_ids=["n1"],
        end_node_ids=["n2"],
    )
    payload = graph.model_dump_json()
    restored = AgentGraph.model_validate_json(payload)

    assert restored == graph
    assert restored.is_valid
    assert isinstance(restored.nodes["n1"].activity, ConceptRef)
    assert is_absent(restored.nodes["n1"].actor)
    assert is_dont_know(restored.nodes["n1"].system)
    assert is_unset(restored.nodes["n1"].reads)
    assert is_absent(restored.nodes["n2"].writes)
    assert is_dont_know(restored.edges["flow"].condition)


def test_evidence_is_diagnostic_and_not_agent_graph_validity_gate() -> None:
    graph = AgentGraph(
        concepts={
            "activity": AgentConcept(
                id="activity", kind="activity", display_label="do work"
            )
        },
        nodes={
            "n": AgentNode(
                id="n",
                activity=ConceptRef(
                    concept_id="activity",
                    evidence=[
                        EvidenceRef(
                            observation_id="missing", quote="not in an observation"
                        )
                    ],
                ),
            )
        },
    )

    assert graph.is_valid
