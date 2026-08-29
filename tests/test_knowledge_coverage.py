"""Focused Phase 7 knowledge-coverage and primary-result tests."""

from __future__ import annotations

import json
from dataclasses import asdict, fields
from pathlib import Path

import pytest

from business_interview.evaluation import (
    CoverageEdge,
    CoverageListSlot,
    CoverageNode,
    InterviewEvaluationContext,
    KnowledgeCoverageView,
    PrimaryEvaluation,
    evaluate_knowledge_coverage,
    evaluate_primary,
)
from business_interview.models import (
    STRUCTURAL_SINK_ID,
    STRUCTURAL_SOURCE_ID,
    AgentGraph,
    BusinessProcessGraph,
    ConceptRef,
    TruthConcept,
    TruthEdge,
    TruthNode,
    business_edge_ids,
    business_node_ids,
    canonicalize_truth_graph,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = PROJECT_ROOT / "src" / "business_interview" / "replay_data" / "seed9004"


def _ref(concept_id: str) -> ConceptRef:
    return ConceptRef(concept_id=concept_id)


def _truth() -> BusinessProcessGraph:
    concepts = {
        concept_id: TruthConcept(
            id=concept_id,
            kind="condition" if concept_id == "condition" else "data",
            canonical_terms=[concept_id],
        )
        for concept_id in (
            "activity_a",
            "activity_b",
            "data_1",
            "data_2",
            "data_3",
            "condition",
        )
    }
    return canonicalize_truth_graph(
        BusinessProcessGraph(
            id="coverage_truth",
            concepts=concepts,
            nodes={
                "n1": TruthNode(
                    id="n1",
                    activity=_ref("activity_a"),
                    reads=[_ref("data_1"), _ref("data_2")],
                    writes=[_ref("data_3")],
                ),
                "n2": TruthNode(id="n2", activity=_ref("activity_b")),
            },
            edges={
                "e1": TruthEdge(
                    id="e1",
                    from_node="n1",
                    to_node="n2",
                    condition=_ref("condition"),
                )
            },
        ),
        entry_node_ids=["n1"],
        exit_node_ids=["n2"],
    )


def _full_view() -> KnowledgeCoverageView:
    return KnowledgeCoverageView(
        nodes_by_truth_id={
            "n1": CoverageNode(
                truth_node_id="n1",
                reads=CoverageListSlot(
                    state="known_values",
                    truth_concept_ids=("data_1", "data_2"),
                ),
                writes=CoverageListSlot(
                    state="known_values",
                    truth_concept_ids=("data_3",),
                ),
            ),
            "n2": CoverageNode(truth_node_id="n2"),
        },
        edges_by_truth_id={"e1": CoverageEdge(truth_edge_id="e1")},
    )


def _replace_node(
    view: KnowledgeCoverageView,
    node_id: str,
    node: CoverageNode | None,
) -> KnowledgeCoverageView:
    nodes = dict(view.nodes_by_truth_id)
    if node is None:
        nodes.pop(node_id, None)
    else:
        nodes[node_id] = node
    return view.model_copy(update={"nodes_by_truth_id": nodes})


def test_seed9004_knowledge_fixture_is_minimal_and_stably_serialized() -> None:
    path = FIXTURE_ROOT / "knowledge_coverage.json"
    text = path.read_text(encoding="utf-8")
    payload = json.loads(text)
    truth = BusinessProcessGraph.model_validate_json(
        (FIXTURE_ROOT / "truth.json").read_text(encoding="utf-8")
    )
    view = KnowledgeCoverageView.model_validate(payload)

    assert set(payload) == {"nodes_by_truth_id", "edges_by_truth_id"}
    assert set(payload["nodes_by_truth_id"]) == set(business_node_ids(truth))
    assert set(payload["edges_by_truth_id"]) == set(business_edge_ids(truth))
    assert set(CoverageNode.model_fields) == {
        "truth_node_id",
        "activity",
        "actor",
        "system",
        "reads",
        "writes",
        "rationale",
    }
    for forbidden in ("skn_", "ske_", "skc_", "description", "terms", "annotation"):
        assert forbidden not in text
    stable = (
        json.dumps(
            view.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    )
    assert text == stable


def test_full_coverage_view_is_one_and_structural_addresses_are_ignored() -> None:
    truth = _truth()
    full = _full_view()
    with_structural = full.model_copy(
        update={
            "nodes_by_truth_id": {
                **full.nodes_by_truth_id,
                STRUCTURAL_SOURCE_ID: CoverageNode(truth_node_id=STRUCTURAL_SOURCE_ID),
                STRUCTURAL_SINK_ID: CoverageNode(truth_node_id=STRUCTURAL_SINK_ID),
            },
            "edges_by_truth_id": {
                **full.edges_by_truth_id,
                "__tau2_structural_boundary__source_001": CoverageEdge(
                    truth_edge_id="__tau2_structural_boundary__source_001"
                ),
            },
        }
    )

    assert evaluate_knowledge_coverage(truth, full) == 1.0
    assert evaluate_knowledge_coverage(truth, with_structural) == 1.0


def test_node_existence_and_missing_node_list_elements_use_source_denominator() -> None:
    truth = _truth()
    full = _full_view()

    missing_n1 = _replace_node(full, "n1", None)

    assert evaluate_knowledge_coverage(truth, full) == 1.0
    # n1 contributes one existence, six slots, and three list elements even
    # when it is missing; n2 and e1 contribute 7 and 2 known addresses.
    assert evaluate_knowledge_coverage(truth, missing_n1) == 9 / 19


def test_scalar_known_and_dont_know_are_the_only_scalar_states() -> None:
    truth = _truth()
    unknown_actor = (
        _full_view().nodes_by_truth_id["n1"].model_copy(update={"actor": "dont_know"})
    )
    view = _replace_node(_full_view(), "n1", unknown_actor)

    assert evaluate_knowledge_coverage(truth, _full_view()) == 1.0
    assert evaluate_knowledge_coverage(truth, view) == 18 / 19


@pytest.mark.parametrize(
    ("slot", "expected"),
    [
        (CoverageListSlot(state="dont_know"), 16 / 19),
        (CoverageListSlot(state="known_absent"), 1.0),
        (
            CoverageListSlot(state="known_values", truth_concept_ids=("data_1",)),
            18 / 19,
        ),
        (
            CoverageListSlot(
                state="known_values", truth_concept_ids=("data_1", "data_2")
            ),
            1.0,
        ),
    ],
    ids=["list-dont-know", "list-known-absent", "list-subset", "list-full"],
)
def test_list_states_preserve_source_element_arithmetic(
    slot: CoverageListSlot,
    expected: float,
) -> None:
    truth = _truth()
    node = _full_view().nodes_by_truth_id["n1"].model_copy(update={"reads": slot})
    view = _replace_node(_full_view(), "n1", node)

    assert evaluate_knowledge_coverage(truth, view) == expected


def test_edge_existence_and_condition_knownness_are_separate_addresses() -> None:
    truth = _truth()
    full = _full_view()
    unknown_condition = full.model_copy(
        update={
            "edges_by_truth_id": {
                "e1": CoverageEdge(
                    truth_edge_id="e1",
                    condition="dont_know",
                )
            }
        }
    )
    missing_edge = full.model_copy(update={"edges_by_truth_id": {}})

    assert evaluate_knowledge_coverage(truth, full) == 1.0
    assert evaluate_knowledge_coverage(truth, unknown_condition) == 18 / 19
    assert evaluate_knowledge_coverage(truth, missing_edge) == 17 / 19


def test_extra_knowledge_entries_do_not_change_truth_iteration() -> None:
    truth = _truth()
    full = _full_view()
    extra = full.model_copy(
        update={
            "nodes_by_truth_id": {
                **full.nodes_by_truth_id,
                "extra_node": CoverageNode(truth_node_id="extra_node"),
            },
            "edges_by_truth_id": {
                **full.edges_by_truth_id,
                "extra_edge": CoverageEdge(truth_edge_id="extra_edge"),
            },
        }
    )

    assert evaluate_knowledge_coverage(truth, extra) == evaluate_knowledge_coverage(
        truth, full
    )


def test_knowledge_coverage_view_does_not_mutate_inputs() -> None:
    truth = _truth()
    view = _full_view()
    truth_before = truth.model_dump(mode="json")
    view_before = view.model_dump(mode="json")

    evaluate_knowledge_coverage(truth, view)

    assert truth.model_dump(mode="json") == truth_before
    assert view.model_dump(mode="json") == view_before


def test_seed9004_primary_evaluator_matches_exactly_41_oracle_fields() -> None:
    truth = BusinessProcessGraph.model_validate_json(
        (FIXTURE_ROOT / "truth.json").read_text(encoding="utf-8")
    )
    agent = AgentGraph.model_validate_json(
        (FIXTURE_ROOT / "agent.json").read_text(encoding="utf-8")
    )
    context = InterviewEvaluationContext.model_validate_json(
        (FIXTURE_ROOT / "evaluation_context.json").read_text(encoding="utf-8")
    )
    knowledge = KnowledgeCoverageView.model_validate_json(
        (FIXTURE_ROOT / "knowledge_coverage.json").read_text(encoding="utf-8")
    )
    expected = json.loads((FIXTURE_ROOT / "expected.json").read_text(encoding="utf-8"))

    result = evaluate_primary(agent, truth, context, knowledge)
    actual = asdict(result)
    oracle = expected["oracle"]["fields"]

    assert len(fields(PrimaryEvaluation)) == 41
    assert len(actual) == 41
    assert set(actual) == set(oracle)
    assert result.knowledge_coverage == oracle["knowledge_coverage"]
    assert actual == oracle


def test_knowledge_change_changes_only_knowledge_coverage() -> None:
    truth = BusinessProcessGraph.model_validate_json(
        (FIXTURE_ROOT / "truth.json").read_text(encoding="utf-8")
    )
    agent = AgentGraph.model_validate_json(
        (FIXTURE_ROOT / "agent.json").read_text(encoding="utf-8")
    )
    context = InterviewEvaluationContext.model_validate_json(
        (FIXTURE_ROOT / "evaluation_context.json").read_text(encoding="utf-8")
    )
    knowledge = KnowledgeCoverageView.model_validate_json(
        (FIXTURE_ROOT / "knowledge_coverage.json").read_text(encoding="utf-8")
    )
    changed_payload = knowledge.model_dump(mode="json")
    changed_payload["nodes_by_truth_id"].pop("ap")
    changed = KnowledgeCoverageView.model_validate(changed_payload)

    baseline = asdict(evaluate_primary(agent, truth, context, knowledge))
    changed_result = asdict(evaluate_primary(agent, truth, context, changed))
    interview_fields = set(baseline) - {"knowledge_coverage"}

    assert baseline["knowledge_coverage"] != changed_result["knowledge_coverage"]
    assert {field: baseline[field] for field in interview_fields} == {
        field: changed_result[field] for field in interview_fields
    }


def test_primary_input_evaluation_does_not_mutate_any_input() -> None:
    truth = BusinessProcessGraph.model_validate_json(
        (FIXTURE_ROOT / "truth.json").read_text(encoding="utf-8")
    )
    agent = AgentGraph.model_validate_json(
        (FIXTURE_ROOT / "agent.json").read_text(encoding="utf-8")
    )
    context = InterviewEvaluationContext.model_validate_json(
        (FIXTURE_ROOT / "evaluation_context.json").read_text(encoding="utf-8")
    )
    knowledge = KnowledgeCoverageView.model_validate_json(
        (FIXTURE_ROOT / "knowledge_coverage.json").read_text(encoding="utf-8")
    )
    before = (
        agent.model_dump(mode="json"),
        truth.model_dump(mode="json"),
        context.model_dump(mode="json"),
        knowledge.model_dump(mode="json"),
    )

    evaluate_primary(agent, truth, context, knowledge)

    after = (
        agent.model_dump(mode="json"),
        truth.model_dump(mode="json"),
        context.model_dump(mode="json"),
        knowledge.model_dump(mode="json"),
    )
    assert after == before


def test_truth_helpers_confirm_fixture_denominator_is_business_only() -> None:
    truth = BusinessProcessGraph.model_validate_json(
        (FIXTURE_ROOT / "truth.json").read_text(encoding="utf-8")
    )

    assert business_node_ids(truth) == ["ap", "cc", "cq", "me", "r", "sq"]
    assert business_edge_ids(truth) == ["e1", "e2", "e3", "e4", "e5", "e6"]
