"""Focused Phase 9 tests for private stakeholder runtime contracts."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from business_interview.models import (
    STRUCTURAL_SINK_ID,
    STRUCTURAL_SOURCE_ID,
    ConceptKind,
)
from business_interview.stakeholders import (  # pyright: ignore[reportMissingImports]
    DONT_KNOW,
    ConceptKnowledgeOverride,
    ForgettingConfig,
    InvalidSemanticAddressError,
    KnowledgeConceptRef,
    KnowledgeDontKnowType,
    ResolvedSemanticAddress,
    ShortcutProvenance,
    StakeholderEdge,
    StakeholderFilter,
    StakeholderKnowledge,
    StakeholderKnowledgeConcept,
    StakeholderKnowledgeGraph,
    StakeholderNode,
    StakeholderProfile,
    UnknownSemanticAddressError,
    is_dont_know,
    is_known_absent,
    parse_semantic_address,
    resolve_semantic_address,
    try_resolve_semantic_address,
    validate_stakeholder_knowledge,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _concept(
    local_id: str,
    truth_id: str,
    kind: ConceptKind,
    *,
    description: str | KnowledgeDontKnowType = "local description",
    terms: tuple[str, ...] | KnowledgeDontKnowType = ("local term",),
) -> StakeholderKnowledgeConcept:
    return StakeholderKnowledgeConcept(
        id=local_id,
        truth_concept_id=truth_id,
        kind=kind,
        description=description,
        terms=terms,
    )


def _knowledge(*, reverse: bool = False) -> StakeholderKnowledge:
    concepts = {
        "concept_a7": _concept("concept_a7", "tc_activity", "activity"),
        "concept_d4": _concept(
            "concept_d4",
            "tc_input",
            "data",
            description=DONT_KNOW,
            terms=("input item", "input"),
        ),
        "concept_w2": _concept("concept_w2", "tc_output", "data"),
        "concept_c9": _concept("concept_c9", "tc_condition", "condition"),
    }
    nodes = {
        STRUCTURAL_SOURCE_ID: StakeholderNode(
            id=STRUCTURAL_SOURCE_ID,
            structural=True,
            structural_role="source",
            protected=True,
        ),
        "node_alpha": StakeholderNode(
            id="node_alpha",
            activity=KnowledgeConceptRef(concept_id="concept_a7"),
            actor=None,
            system=DONT_KNOW,
            reads=[KnowledgeConceptRef(concept_id="concept_d4")],
            writes=[KnowledgeConceptRef(concept_id="concept_w2")],
            rationale=DONT_KNOW,
        ),
        "node_beta": StakeholderNode(
            id="node_beta",
            activity=KnowledgeConceptRef(concept_id="concept_a7"),
            reads=None,
        ),
        "node_gamma": StakeholderNode(
            id="node_gamma",
            activity=None,
            writes=None,
        ),
        STRUCTURAL_SINK_ID: StakeholderNode(
            id=STRUCTURAL_SINK_ID,
            structural=True,
            structural_role="sink",
            protected=True,
        ),
    }
    edges = {
        "__tau2_structural_boundary__source_001": StakeholderEdge(
            id="__tau2_structural_boundary__source_001",
            from_node=STRUCTURAL_SOURCE_ID,
            to_node="node_alpha",
            edge_kind="structural_boundary",
            structural_only=True,
            protected=True,
        ),
        "edge_condition": StakeholderEdge(
            id="edge_condition",
            from_node="node_alpha",
            to_node="node_beta",
            condition=KnowledgeConceptRef(concept_id="concept_c9"),
        ),
        "edge_shortcut": StakeholderEdge(
            id="edge_shortcut",
            from_node="node_beta",
            to_node="node_gamma",
            edge_kind="shortcut",
            is_shortcut=True,
            contracted_nodes=("node_removed",),
            derived_from_edges=("edge_before", "edge_after"),
        ),
        "__tau2_structural_boundary__sink_001": StakeholderEdge(
            id="__tau2_structural_boundary__sink_001",
            from_node="node_gamma",
            to_node=STRUCTURAL_SINK_ID,
            edge_kind="structural_boundary",
            structural_only=True,
            protected=True,
        ),
    }
    provenance = {
        "edge_shortcut": ShortcutProvenance(
            contracted_nodes=("node_removed",),
            derived_from_edges=("edge_before", "edge_after"),
        )
    }
    node_truth_ids = {
        "node_alpha": "r",
        "node_beta": "cc",
        "node_gamma": "cq",
    }
    edge_truth_ids = {
        "__tau2_structural_boundary__source_001": "boundary_source",
        "edge_condition": "e1",
        "edge_shortcut": "__shortcut__",
        "__tau2_structural_boundary__sink_001": "boundary_sink",
    }
    if reverse:
        concepts = dict(reversed(list(concepts.items())))
        nodes = dict(reversed(list(nodes.items())))
        edges = dict(reversed(list(edges.items())))
        node_truth_ids = dict(reversed(list(node_truth_ids.items())))
        edge_truth_ids = dict(reversed(list(edge_truth_ids.items())))
    graph = StakeholderKnowledgeGraph(
        id="private_world",
        name="Private world",
        nodes=nodes,
        edges=edges,
        concepts=concepts,
        node_truth_ids=node_truth_ids,
        edge_truth_ids=edge_truth_ids,
        shortcut_provenance=provenance,
    )
    return StakeholderKnowledge(graph=graph)


def test_stakeholder_profile_round_trip_and_visibility_semantics() -> None:
    profile = StakeholderProfile(
        stakeholder_id="profile_sales",
        name="Sales employee",
        role="sales",
        visible_node_ids=("cq", "r", "cc"),
        visible_edge_ids=("e2", "e1"),
        visible_node_attributes={
            "cq": ("writes", "activity", "reads"),
            "r": ("actor",),
        },
        visible_edge_attributes={"e2": ("condition",)},
        concept_overrides={
            "tc_customer": ConceptKnowledgeOverride(
                description_known=False,
                terms_known=False,
                local_terms=("customer master", "customer"),
            )
        },
        forgetting=ForgettingConfig(
            baseline_forget_probability=0.2,
            node_forget_probability=0.3,
            edge_forget_probability=0.1,
            property_forget_probability=0.4,
            max_retries=7,
            allow_shortcut_contraction=False,
        ),
    )
    restored = StakeholderProfile.model_validate_json(profile.model_dump_json())

    assert restored == profile
    assert isinstance(restored, StakeholderFilter)
    assert restored.visible_node_ids == ("cc", "cq", "r")
    assert restored.node_properties_for("cq") == {"activity", "reads", "writes"}
    assert restored.edge_properties_for("e2") == {"condition"}
    assert restored.concept_overrides["tc_customer"].terminology_known is False
    assert restored.forgetting.forget_probability == 0.2
    assert restored.forgetting.effective_node_probability == 0.3
    assert restored.forgetting.effective_edge_probability == 0.2
    assert restored.forgetting.safe_shortcut_contraction is False
    assert (
        ForgettingConfig.model_validate(
            {"forget_probability": 0.2}
        ).baseline_forget_probability
        == 0.2
    )


def test_forgetting_probabilities_and_retries_are_bounded() -> None:
    probability_fields = (
        "baseline_forget_probability",
        "node_forget_probability",
        "edge_forget_probability",
        "property_forget_probability",
    )
    for field_name in probability_fields:
        with pytest.raises(ValidationError):
            ForgettingConfig.model_validate({field_name: -0.01})
        with pytest.raises(ValidationError):
            ForgettingConfig.model_validate({field_name: 1.01})
    with pytest.raises(ValidationError):
        ForgettingConfig(max_retries=0)

    assert ForgettingConfig(baseline_forget_probability=0.0).allow_shortcut_contraction


def test_knowledge_round_trip_preserves_values_absence_unknown_and_private_mappings() -> (
    None
):
    knowledge = _knowledge()
    restored = StakeholderKnowledge.model_validate_json(knowledge.model_dump_json())
    node = restored.graph.nodes["node_alpha"]

    assert restored == knowledge
    assert restored.graph.node_truth_ids["node_alpha"] == "r"
    assert restored.graph.edge_truth_ids["edge_condition"] == "e1"
    assert restored.graph.concepts["concept_d4"].truth_concept_id == "tc_input"
    assert isinstance(node.activity, KnowledgeConceptRef)
    assert is_known_absent(node.actor)
    assert is_dont_know(node.system)
    assert isinstance(node.reads, list)
    assert isinstance(node.reads[0], KnowledgeConceptRef)
    assert restored.graph.edges["edge_shortcut"].is_shortcut
    assert restored.graph.shortcut_provenance["edge_shortcut"].contracted_nodes == (
        "node_removed",
    )
    validate_stakeholder_knowledge(restored)


def test_knowledge_serialization_is_insertion_order_independent() -> None:
    first = _knowledge()
    second = _knowledge(reverse=True)

    assert first == second
    assert first.model_dump_json() == second.model_dump_json()


def test_structural_metadata_is_explicit_and_protected() -> None:
    graph = _knowledge().graph
    source = graph.nodes[STRUCTURAL_SOURCE_ID]
    sink = graph.nodes[STRUCTURAL_SINK_ID]
    source_edge = graph.edges["__tau2_structural_boundary__source_001"]
    sink_edge = graph.edges["__tau2_structural_boundary__sink_001"]

    assert source.is_structural and source.structural_role == "source"
    assert sink.is_structural and sink.structural_role == "sink"
    assert source.protected and sink.protected
    assert source_edge.is_structural and source_edge.protected
    assert sink_edge.is_structural and sink_edge.protected
    assert source_edge.condition is None
    assert sink_edge.condition is None
    assert graph.is_valid


def test_semantic_address_resolver_addresses_all_required_shapes() -> None:
    graph = _knowledge().graph
    expected = {
        "node:node_alpha": "node",
        "node:node_alpha:activity": "node_slot",
        "node:node_alpha:actor": "node_slot",
        "node:node_alpha:system": "node_slot",
        "node:node_alpha:reads": "node_slot",
        "node:node_alpha:reads:concept_d4": "node_element",
        "node:node_alpha:writes": "node_slot",
        "node:node_alpha:writes:concept_w2": "node_element",
        "node:node_alpha:rationale": "node_slot",
        "edge:edge_condition": "edge",
        "edge:edge_condition:condition": "edge_slot",
        "concept_d4": "concept",
    }

    for address, kind in expected.items():
        resolved = resolve_semantic_address(graph, address)
        assert isinstance(resolved, ResolvedSemanticAddress)
        assert resolved.kind == kind
        assert graph.resolve(address) == resolved

    assert graph.resolve("node:node_alpha:actor").value is None
    assert graph.resolve("node:node_alpha:system").value == DONT_KNOW
    assert (
        graph.resolve("edge:edge_condition:condition").value.concept_id == "concept_c9"
    )


def test_invalid_and_unknown_semantic_addresses_are_rejected_distinctly() -> None:
    graph = _knowledge().graph

    for address in (
        "",
        "node:",
        "node:node_alpha:unknown",
        "node:node_alpha:reads:x:y",
    ):
        with pytest.raises(InvalidSemanticAddressError):
            resolve_semantic_address(graph, address)
    for address in (
        "node:missing",
        "node:node_alpha:reads:missing",
        "edge:missing:condition",
        "missing_concept",
    ):
        with pytest.raises(UnknownSemanticAddressError):
            resolve_semantic_address(graph, address)

    with pytest.raises(InvalidSemanticAddressError):
        parse_semantic_address("edge:edge_condition:wrong")
    assert try_resolve_semantic_address(graph, "node:missing") is None
    assert try_resolve_semantic_address(graph, "node:node_alpha:bad") is None


def test_semantic_id_namespace_is_complete_and_local() -> None:
    graph = _knowledge().graph
    ids = graph.semantic_ids()

    assert "node:node_alpha" in ids
    assert "node:node_alpha:reads:concept_d4" in ids
    assert "edge:edge_condition:condition" in ids
    assert "concept_d4" in ids
    assert "node:r" not in ids
    assert all(
        local_id not in graph.node_truth_ids.values()
        for local_id in graph.nodes
        if local_id not in {STRUCTURAL_SOURCE_ID, STRUCTURAL_SINK_ID}
    )


def test_runtime_package_does_not_depend_on_phase_fixture_paths() -> None:
    for path in (PROJECT_ROOT / "src" / "business_interview" / "stakeholders").rglob(
        "*.py"
    ):
        assert "tests/fixtures" not in path.read_text(encoding="utf-8")
