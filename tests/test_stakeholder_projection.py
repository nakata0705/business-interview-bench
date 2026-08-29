"""Focused Phase 10 tests for Truth-to-stakeholder projection."""

# The workspace-level auxiliary Pyright runner can miss freshly added sibling
# modules; project-level ``uv run pyright`` remains the authoritative check.
# pyright: reportMissingImports=false

from __future__ import annotations

import json
import random
from collections.abc import Mapping, MutableMapping
from dataclasses import asdict
from pathlib import Path
from typing import cast

import pytest

from business_interview.evaluation import (
    evaluate_graph,
    evaluate_interview,
    evaluate_knowledge_coverage,
    evaluate_primary,
)
from business_interview.evaluation import (
    knowledge_coverage_view as evaluator_knowledge_coverage_view,
)
from business_interview.models import (
    STRUCTURAL_SINK_ID,
    STRUCTURAL_SOURCE_ID,
    AgentGraph,
    BusinessProcessGraph,
    ConceptKind,
    ConceptRef,
    InterviewEvaluationContext,
    TruthConcept,
    TruthEdge,
    TruthNode,
    business_edge_ids,
    business_node_ids,
    canonicalize_truth_graph,
)
from business_interview.scenarios import get_scenario
from business_interview.stakeholders import (
    ConceptKnowledgeOverride,
    EdgeProperty,
    ForgettingConfig,
    KnowledgeConceptRef,
    NodeProperty,
    StakeholderProfile,
    is_dont_know,
    is_known_absent,
    validate_stakeholder_knowledge,
)
from business_interview.stakeholders.projection import (
    KnowledgeProjectionError,
    knowledge_coverage_view,
    project_knowledge,
)

_NODE_PROPERTIES: tuple[NodeProperty, ...] = (
    "activity",
    "actor",
    "system",
    "reads",
    "writes",
    "rationale",
)


def _ref(concept_id: str) -> ConceptRef:
    return ConceptRef(concept_id=concept_id)


def _concept(
    concept_id: str,
    kind: ConceptKind = "data",
    *,
    description: str | None = None,
    terms: list[str] | None = None,
) -> TruthConcept:
    return TruthConcept(
        id=concept_id,
        kind=kind,
        description=description or f"Description for {concept_id}",
        canonical_terms=terms or [f"term for {concept_id}"],
    )


def _linear_truth(*, conditioned: bool = False) -> BusinessProcessGraph:
    concepts = {
        "activity_a": _concept("activity_a", "activity"),
        "activity_b": _concept("activity_b", "activity"),
        "activity_c": _concept("activity_c", "activity"),
        "actor_sales": _concept("actor_sales", "actor"),
        "input": _concept("input"),
        "output": _concept("output"),
        "condition": _concept("condition", "condition"),
        "unused": _concept("unused"),
    }
    return canonicalize_truth_graph(
        BusinessProcessGraph(
            id="linear",
            name="Linear workflow",
            concepts=concepts,
            nodes={
                "a": TruthNode(
                    id="a",
                    activity=_ref("activity_a"),
                    actor=_ref("actor_sales"),
                    reads=[_ref("input")],
                    writes=None,
                ),
                "b": TruthNode(
                    id="b",
                    activity=_ref("activity_b"),
                    actor=None,
                    writes=[_ref("output")],
                ),
                "c": TruthNode(
                    id="c",
                    activity=_ref("activity_c"),
                    actor=_ref("actor_sales"),
                ),
            },
            edges={
                "ab": TruthEdge(
                    id="ab",
                    from_node="a",
                    to_node="b",
                    condition=_ref("condition") if conditioned else None,
                ),
                "bc": TruthEdge(id="bc", from_node="b", to_node="c"),
            },
        ),
        entry_node_ids=["a"],
        exit_node_ids=["c"],
    )


def _serial_truth(node_ids: tuple[str, ...]) -> BusinessProcessGraph:
    concepts = {
        f"activity_{node_id}": _concept(f"activity_{node_id}", "activity")
        for node_id in node_ids
    }
    nodes = {
        node_id: TruthNode(
            id=node_id,
            activity=_ref(f"activity_{node_id}"),
        )
        for node_id in node_ids
    }
    edges = {
        f"{left}{right}": TruthEdge(
            id=f"{left}{right}",
            from_node=left,
            to_node=right,
        )
        for left, right in zip(node_ids, node_ids[1:])
    }
    return canonicalize_truth_graph(
        BusinessProcessGraph(
            id="serial",
            name="Serial workflow",
            concepts=concepts,
            nodes=nodes,
            edges=edges,
        ),
        entry_node_ids=[node_ids[0]],
        exit_node_ids=[node_ids[-1]],
    )


def _branch_truth() -> BusinessProcessGraph:
    concepts = {
        f"activity_{node_id}": _concept(f"activity_{node_id}", "activity")
        for node_id in ("start", "branch", "left", "right", "end")
    }
    return canonicalize_truth_graph(
        BusinessProcessGraph(
            id="branch",
            name="Branch workflow",
            concepts=concepts,
            nodes={
                node_id: TruthNode(
                    id=node_id,
                    activity=_ref(f"activity_{node_id}"),
                )
                for node_id in ("start", "branch", "left", "right", "end")
            },
            edges={
                "start_branch": TruthEdge(
                    id="start_branch", from_node="start", to_node="branch"
                ),
                "branch_left": TruthEdge(
                    id="branch_left", from_node="branch", to_node="left"
                ),
                "branch_right": TruthEdge(
                    id="branch_right", from_node="branch", to_node="right"
                ),
                "left_end": TruthEdge(id="left_end", from_node="left", to_node="end"),
                "right_end": TruthEdge(
                    id="right_end", from_node="right", to_node="end"
                ),
            },
        ),
        entry_node_ids=["start"],
        exit_node_ids=["end"],
    )


def _merge_truth() -> BusinessProcessGraph:
    concepts = {
        f"activity_{node_id}": _concept(f"activity_{node_id}", "activity")
        for node_id in ("left", "right", "merge", "end")
    }
    return canonicalize_truth_graph(
        BusinessProcessGraph(
            id="merge",
            name="Merge workflow",
            concepts=concepts,
            nodes={
                node_id: TruthNode(
                    id=node_id,
                    activity=_ref(f"activity_{node_id}"),
                )
                for node_id in ("left", "right", "merge", "end")
            },
            edges={
                "left_merge": TruthEdge(
                    id="left_merge", from_node="left", to_node="merge"
                ),
                "right_merge": TruthEdge(
                    id="right_merge", from_node="right", to_node="merge"
                ),
                "merge_end": TruthEdge(
                    id="merge_end", from_node="merge", to_node="end"
                ),
            },
        ),
        entry_node_ids=["left", "right"],
        exit_node_ids=["end"],
    )


def _parallel_truth() -> BusinessProcessGraph:
    concepts = {
        "activity_a": _concept("activity_a", "activity"),
        "activity_b": _concept("activity_b", "activity"),
    }
    return canonicalize_truth_graph(
        BusinessProcessGraph(
            id="parallel",
            name="Parallel-edge workflow",
            concepts=concepts,
            nodes={
                "a": TruthNode(id="a", activity=_ref("activity_a")),
                "b": TruthNode(id="b", activity=_ref("activity_b")),
            },
            edges={
                "e1": TruthEdge(id="e1", from_node="a", to_node="b"),
                "e2": TruthEdge(id="e2", from_node="a", to_node="b"),
            },
        ),
        entry_node_ids=["a"],
        exit_node_ids=["b"],
    )


def _profile(
    truth: BusinessProcessGraph,
    *,
    visible_nodes: tuple[str, ...] | None = None,
    visible_edges: tuple[str, ...] | None = None,
    node_attributes: Mapping[str, tuple[NodeProperty, ...]] | None = None,
    edge_attributes: Mapping[str, tuple[EdgeProperty, ...]] | None = None,
    forgetting: ForgettingConfig | None = None,
    overrides: Mapping[str, ConceptKnowledgeOverride] | None = None,
) -> StakeholderProfile:
    return StakeholderProfile(
        stakeholder_id="projection_test",
        name="Projection test stakeholder",
        role="tester",
        visible_node_ids=(
            visible_nodes
            if visible_nodes is not None
            else tuple(business_node_ids(truth))
        ),
        visible_edge_ids=(
            visible_edges
            if visible_edges is not None
            else tuple(business_edge_ids(truth))
        ),
        visible_node_attributes=node_attributes or {},
        visible_edge_attributes=edge_attributes or {},
        concept_overrides=overrides or {},
        forgetting=forgetting or ForgettingConfig(),
    )


def _fully_known_profile(
    truth: BusinessProcessGraph,
    *,
    forgetting: ForgettingConfig | None = None,
    overrides: Mapping[str, ConceptKnowledgeOverride] | None = None,
) -> StakeholderProfile:
    return _profile(
        truth,
        node_attributes={
            node_id: _NODE_PROPERTIES for node_id in business_node_ids(truth)
        },
        edge_attributes={
            edge_id: ("condition",) for edge_id in business_edge_ids(truth)
        },
        forgetting=forgetting,
        overrides=overrides,
    )


def _reverse_graph_collections(truth: BusinessProcessGraph) -> BusinessProcessGraph:
    payload = truth.model_dump()
    for field_name in ("nodes", "edges", "concepts"):
        payload[field_name] = dict(reversed(list(payload[field_name].items())))
    return BusinessProcessGraph.model_validate(payload)


def _reverse_profile_collections(profile: StakeholderProfile) -> StakeholderProfile:
    payload = profile.model_dump()
    for field_name in ("visible_node_ids", "visible_edge_ids"):
        payload[field_name] = list(reversed(payload[field_name]))
    for field_name in (
        "visible_node_attributes",
        "visible_edge_attributes",
        "concept_overrides",
    ):
        payload[field_name] = dict(reversed(list(payload[field_name].items())))
    return StakeholderProfile.model_validate(payload)


class _ScriptedRandom:
    def __init__(self, values: list[float]) -> None:
        self._values = iter(values)

    def random(self) -> float:
        return next(self._values)


def test_no_forgetting_projection_is_valid_and_reproducible() -> None:
    truth = _linear_truth()
    profile = _fully_known_profile(truth)

    first = project_knowledge(truth, profile, seed=17)
    second = project_knowledge(truth, profile, seed=17)

    assert first == second
    assert first.model_dump_json() == second.model_dump_json()
    assert type(first).model_validate_json(first.model_dump_json()) == first
    assert first.generation_seed == 17
    assert first.generation_rng_source == "random.Random(seed)"
    assert first.graph.is_valid
    validate_stakeholder_knowledge(first)
    assert set(first.graph.node_truth_ids.values()) >= {
        "a",
        "b",
        "c",
        STRUCTURAL_SOURCE_ID,
        STRUCTURAL_SINK_ID,
    }
    assert not any(edge.is_shortcut for edge in first.graph.edges.values())
    assert {concept.truth_concept_id for concept in first.graph.concepts.values()} == {
        "activity_a",
        "activity_b",
        "activity_c",
        "actor_sales",
        "input",
        "output",
    }


def test_node_visibility_masks_by_safe_serial_contraction() -> None:
    truth = _linear_truth()
    profile = _fully_known_profile(truth).model_copy(
        update={"visible_node_ids": ("a", "c")}
    )

    knowledge = project_knowledge(truth, profile, seed=1)
    graph = knowledge.graph

    assert "b" not in graph.node_truth_ids.values()
    shortcuts = [edge for edge in graph.edges.values() if edge.is_shortcut]
    assert len(shortcuts) == 1
    shortcut = shortcuts[0]
    assert shortcut.edge_kind == "shortcut"
    assert shortcut.contracted_nodes == ("b",)
    assert shortcut.derived_from_edges == ("ab", "bc")
    assert graph.is_valid


def test_edge_visibility_masks_an_edge_without_repairing_topology() -> None:
    truth = _parallel_truth()
    profile = _fully_known_profile(truth).model_copy(
        update={"visible_edge_ids": ("e1",)}
    )

    knowledge = project_knowledge(truth, profile, seed=1)

    assert "e1" in knowledge.graph.edge_truth_ids.values()
    assert "e2" not in knowledge.graph.edge_truth_ids.values()
    assert knowledge.graph.is_valid


def test_property_visibility_preserves_known_value_absence_and_unknown() -> None:
    truth = _linear_truth(conditioned=True)
    profile = _profile(
        truth,
        node_attributes={
            "a": ("activity", "actor", "reads", "writes"),
            "b": ("actor", "writes"),
        },
        edge_attributes={"ab": ("condition",)},
    )

    knowledge = project_knowledge(truth, profile, seed=2)
    node_a = knowledge.graph.nodes[
        next(
            local
            for local, truth_id in knowledge.graph.node_truth_ids.items()
            if truth_id == "a"
        )
    ]
    node_b = knowledge.graph.nodes[
        next(
            local
            for local, truth_id in knowledge.graph.node_truth_ids.items()
            if truth_id == "b"
        )
    ]
    edge_ab = knowledge.graph.edges[
        next(
            local
            for local, truth_id in knowledge.graph.edge_truth_ids.items()
            if truth_id == "ab"
        )
    ]
    edge_bc = knowledge.graph.edges[
        next(
            local
            for local, truth_id in knowledge.graph.edge_truth_ids.items()
            if truth_id == "bc"
        )
    ]

    assert isinstance(node_a.activity, KnowledgeConceptRef)
    assert isinstance(node_a.reads, tuple)
    assert is_known_absent(node_a.writes)
    assert is_dont_know(node_a.system)
    assert is_dont_know(node_b.activity)
    assert is_known_absent(node_b.actor)
    assert isinstance(node_b.writes, tuple)
    assert isinstance(edge_ab.condition, KnowledgeConceptRef)
    assert is_dont_know(edge_bc.condition)


def test_concept_overrides_are_independent_and_unreferenced_concepts_are_omitted() -> (
    None
):
    truth = _linear_truth()
    profile = _fully_known_profile(
        truth,
        overrides={
            "activity_a": ConceptKnowledgeOverride(
                description_known=False,
                terms_known=True,
                local_terms=("local activity",),
            ),
            "input": ConceptKnowledgeOverride(
                description_known=True,
                terms_known=False,
            ),
        },
    )

    knowledge = project_knowledge(truth, profile, seed=3)
    by_truth = {
        concept.truth_concept_id: concept
        for concept in knowledge.graph.concepts.values()
    }

    assert "unused" not in by_truth
    assert is_dont_know(by_truth["activity_a"].description)
    assert by_truth["activity_a"].terms == ("local activity",)
    assert isinstance(by_truth["input"].description, str)
    assert is_dont_know(by_truth["input"].terms)
    assert by_truth["activity_a"].kind == "activity"


def test_local_ids_and_serialization_ignore_collection_insertion_order() -> None:
    truth = _linear_truth()
    profile = _fully_known_profile(truth)
    reversed_truth = _reverse_graph_collections(truth)
    reversed_profile = _reverse_profile_collections(profile)

    first = project_knowledge(truth, profile, seed=5)
    second = project_knowledge(reversed_truth, reversed_profile, seed=5)

    assert first == second
    assert first.model_dump_json() == second.model_dump_json()
    assert all(
        local_id.startswith("skn_")
        for local_id, truth_id in first.graph.node_truth_ids.items()
        if truth_id not in {STRUCTURAL_SOURCE_ID, STRUCTURAL_SINK_ID}
    )
    assert all(local_id.startswith("ske_") for local_id in first.graph.edge_truth_ids)
    assert all(local_id.startswith("skc_") for local_id in first.graph.concepts)
    assert all(
        local_id not in set(first.graph.node_truth_ids.values())
        for local_id in first.graph.nodes
        if local_id not in {STRUCTURAL_SOURCE_ID, STRUCTURAL_SINK_ID}
    )


def test_opaque_id_allocator_avoids_truth_id_collisions() -> None:
    truth = _serial_truth(("skn_001", "skn_002"))

    knowledge = project_knowledge(truth, _fully_known_profile(truth), seed=6)

    local_ids = set(knowledge.graph.nodes) | set(knowledge.graph.edges)
    local_ids.update(knowledge.graph.concepts)
    truth_ids = (set(truth.nodes) | set(truth.edges) | set(truth.concepts)) - {
        STRUCTURAL_SOURCE_ID,
        STRUCTURAL_SINK_ID,
    }
    assert not local_ids.intersection(truth_ids)
    assert knowledge.graph.is_valid


def test_seed_changes_forgetting_without_touching_global_random_state() -> None:
    truth = _linear_truth()
    profile = _fully_known_profile(
        truth,
        forgetting=ForgettingConfig(property_forget_probability=0.5),
    )

    random.seed(90210)
    before = random.getstate()
    first = project_knowledge(truth, profile, seed=1)
    after = random.getstate()
    second = project_knowledge(truth, profile, seed=2)

    assert before == after
    assert first.graph != second.graph
    assert first.model_dump_json() != second.model_dump_json()


def test_structural_boundaries_are_always_retained_and_protected() -> None:
    truth = _linear_truth()
    profile = _fully_known_profile(truth).model_copy(
        update={"visible_node_ids": ("a", "c")}
    )

    graph = project_knowledge(truth, profile, seed=7).graph

    assert STRUCTURAL_SOURCE_ID in graph.nodes
    assert STRUCTURAL_SINK_ID in graph.nodes
    assert graph.nodes[STRUCTURAL_SOURCE_ID].protected
    assert graph.nodes[STRUCTURAL_SINK_ID].protected
    structural_edges = [edge for edge in graph.edges.values() if edge.is_structural]
    assert structural_edges
    assert all(edge.protected for edge in structural_edges)
    assert all(edge.condition is None for edge in structural_edges)


def test_multiple_serial_contractions_retain_complete_shortcut_provenance() -> None:
    truth = _serial_truth(("a", "b", "c", "d"))
    profile = _fully_known_profile(truth).model_copy(
        update={"visible_node_ids": ("a", "d")}
    )

    knowledge = project_knowledge(truth, profile, seed=8)
    shortcuts = [edge for edge in knowledge.graph.edges.values() if edge.is_shortcut]

    assert len(shortcuts) == 1
    shortcut = shortcuts[0]
    assert shortcut.contracted_nodes == ("b", "c")
    assert shortcut.derived_from_edges == ("ab", "bc", "cd")
    local_id = shortcut.id
    assert knowledge.graph.shortcut_provenance[local_id].contracted_nodes == (
        "b",
        "c",
    )
    assert knowledge.graph.shortcut_provenance[local_id].derived_from_edges == (
        "ab",
        "bc",
        "cd",
    )


def _always_forget_profile(truth: BusinessProcessGraph) -> StakeholderProfile:
    return _fully_known_profile(
        truth,
        forgetting=ForgettingConfig(node_forget_probability=1.0, max_retries=1),
    )


@pytest.mark.parametrize(
    ("truth_factory", "reason_fragment"),
    [
        (_branch_truth, "indegree=1, outdegree=2"),
        (_merge_truth, "indegree=2, outdegree=1"),
        (lambda: _linear_truth(conditioned=True), "conditioned incident path"),
    ],
)
def test_unsafe_branch_merge_and_conditioned_contractions_are_rejected(
    truth_factory, reason_fragment: str
) -> None:
    truth = truth_factory()

    with pytest.raises(KnowledgeProjectionError) as error:
        project_knowledge(truth, _always_forget_profile(truth), seed=9)

    assert error.value.attempts == 1
    assert any(reason_fragment in reason for reason in error.value.reasons)


def test_shortcut_contraction_can_be_disabled_without_silent_repair() -> None:
    truth = _linear_truth()
    profile = _fully_known_profile(
        truth,
        forgetting=ForgettingConfig(
            node_forget_probability=1.0,
            max_retries=1,
            allow_shortcut_contraction=False,
        ),
    )

    with pytest.raises(KnowledgeProjectionError) as error:
        project_knowledge(truth, profile, seed=10)

    assert "shortcut contraction is disabled" in error.value.reasons


def test_retry_uses_one_rng_stream_and_succeeds_after_invalid_sample() -> None:
    truth = _branch_truth()
    profile = _fully_known_profile(
        truth,
        forgetting=ForgettingConfig(node_forget_probability=0.5, max_retries=2),
    )
    # Sorted business node IDs start with branch.  The first five values
    # forget branch but retain the other nodes, so that sample is rejected;
    # the next five values retain every node.
    scripted = _ScriptedRandom([0.1, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9])

    knowledge = project_knowledge(truth, profile, rng=cast(random.Random, scripted))

    assert knowledge.graph.is_valid
    assert knowledge.generation_seed is None
    assert knowledge.generation_rng_source == "caller-provided random source"


def test_retry_exhaustion_raises_explicit_error() -> None:
    truth = _branch_truth()
    profile = _fully_known_profile(
        truth,
        forgetting=ForgettingConfig(node_forget_probability=1.0, max_retries=2),
    )

    with pytest.raises(KnowledgeProjectionError) as error:
        project_knowledge(truth, profile, seed=11)

    assert error.value.attempts == 2
    assert len(error.value.reasons) == 2
    assert "indegree=1, outdegree=2" in error.value.reasons[0]


def test_invalid_truth_is_rejected_before_projection() -> None:
    invalid = BusinessProcessGraph(
        id="invalid",
        nodes={"a": TruthNode(id="a")},
        edges={},
    )
    profile = StakeholderProfile(stakeholder_id="s", name="Stakeholder")

    with pytest.raises(ValueError, match="Truth graph is not canonical"):
        project_knowledge(invalid, profile, seed=1)


def test_projected_knowledge_is_deeply_immutable() -> None:
    truth = _linear_truth()
    profile = _fully_known_profile(truth)
    knowledge = project_knowledge(truth, profile, seed=12)

    with pytest.raises(TypeError):
        cast(MutableMapping[str, object], knowledge.graph.nodes)["new"] = object()
    with pytest.raises(TypeError):
        cast(MutableMapping[str, object], knowledge.graph.node_truth_ids)["new"] = (
            "truth",
        )
    local_a = next(
        local
        for local, truth_id in knowledge.graph.node_truth_ids.items()
        if truth_id == "a"
    )
    reads = knowledge.graph.nodes[local_a].reads
    assert isinstance(reads, tuple)
    with pytest.raises(AttributeError):
        getattr(reads, "append")(KnowledgeConceptRef(concept_id="skc_001"))


def test_coverage_view_is_derived_from_projected_knowledge() -> None:
    truth = _linear_truth()
    profile = _fully_known_profile(truth)
    knowledge = project_knowledge(truth, profile, seed=13)

    view = knowledge_coverage_view(truth, knowledge)

    assert evaluator_knowledge_coverage_view(truth, knowledge) == view
    assert set(view.nodes_by_truth_id) == set(business_node_ids(truth))
    assert set(view.edges_by_truth_id) == set(business_edge_ids(truth))
    assert evaluate_knowledge_coverage(truth, view) == 1.0
    assert view.nodes_by_truth_id["a"].reads.state == "known_values"
    assert view.nodes_by_truth_id["a"].writes.state == "known_absent"
    assert view.edges_by_truth_id["ab"].condition == "known"


def test_coverage_view_tracks_hidden_elements_and_unknown_properties() -> None:
    truth = _linear_truth()
    profile = _profile(
        truth,
        visible_nodes=("a", "c"),
        node_attributes={"a": ("activity",)},
        edge_attributes={},
    )
    knowledge = project_knowledge(truth, profile, seed=14)

    view = knowledge_coverage_view(truth, knowledge)

    assert "b" not in view.nodes_by_truth_id
    assert view.nodes_by_truth_id["a"].activity == "known"
    assert view.nodes_by_truth_id["a"].actor == "dont_know"
    assert "ab" not in view.edges_by_truth_id
    assert "bc" not in view.edges_by_truth_id


def test_projected_address_resolver_uses_opaque_local_namespace() -> None:
    truth = _linear_truth()
    knowledge = project_knowledge(truth, _fully_known_profile(truth), seed=15)
    local_a = next(
        local
        for local, truth_id in knowledge.graph.node_truth_ids.items()
        if truth_id == "a"
    )
    local_edge = next(
        local
        for local, truth_id in knowledge.graph.edge_truth_ids.items()
        if truth_id == "ab"
    )

    assert knowledge.resolve(f"node:{local_a}").kind == "node"
    assert knowledge.resolve(f"node:{local_a}:activity").kind == "node_slot"
    assert knowledge.resolve(f"node:{local_a}:reads").kind == "node_slot"
    assert knowledge.resolve(f"edge:{local_edge}:condition").kind == "edge_slot"
    assert knowledge.graph.semantic_ids()


def test_seed_none_is_private_and_explicitly_non_reproducible_mode() -> None:
    truth = _linear_truth()
    profile = _fully_known_profile(
        truth,
        forgetting=ForgettingConfig(property_forget_probability=0.5),
    )

    knowledge = project_knowledge(truth, profile)

    assert knowledge.generation_seed is None
    assert knowledge.generation_rng_source == "random.Random(None)"
    assert knowledge.graph.is_valid


def test_seed9004_catalog_projection_preserves_all_evaluator_parity() -> None:
    scenario = get_scenario("quotation_workflow_1")
    truth = scenario.truth
    profile = _profile(
        truth,
        node_attributes={
            "r": ("activity", "actor", "writes"),
            "cc": ("activity", "actor", "system", "reads"),
            "cq": ("activity", "actor", "system", "reads", "writes"),
            "ap": ("activity", "actor", "rationale"),
            "sq": ("activity", "actor", "system"),
            "me": ("activity", "actor", "system", "writes"),
        },
        edge_attributes={
            "e1": (),
            "e2": (),
            "e3": ("condition",),
            "e4": ("condition",),
            "e5": (),
            "e6": ("condition",),
        },
    )
    knowledge = project_knowledge(truth, profile, seed=0)
    coverage = knowledge_coverage_view(truth, knowledge)
    fixture_root = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "business_interview"
        / "replay_data"
        / "seed9004"
    )
    expected = json.loads((fixture_root / "expected.json").read_text(encoding="utf-8"))[
        "oracle"
    ]["fields"]
    agent = AgentGraph.model_validate_json(
        (fixture_root / "agent.json").read_text(encoding="utf-8")
    )
    context = InterviewEvaluationContext.model_validate_json(
        (fixture_root / "evaluation_context.json").read_text(encoding="utf-8")
    )

    graph_result = asdict(evaluate_graph(agent, truth))
    interview_result = asdict(evaluate_interview(agent, truth, context))
    primary_result = asdict(evaluate_primary(agent, truth, context, coverage))

    assert graph_result == {key: expected[key] for key in graph_result}
    assert interview_result == {key: expected[key] for key in interview_result}
    assert primary_result == expected
