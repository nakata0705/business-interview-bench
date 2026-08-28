"""Focused tests for the standalone scenario/task catalog."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from business_interview.evaluation import KnowledgeCoverageView, evaluate_primary
from business_interview.models import (
    AgentGraph,
    BusinessProcessGraph,
    InterviewEvaluationContext,
    business_edge_ids,
    business_entry_node_ids,
    business_exit_node_ids,
    business_node_ids,
    validate_canonical_graph,
)
from business_interview.scenarios import (  # pyright: ignore[reportMissingImports]
    UnknownScenarioError,
    get_scenario,
    list_scenarios,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SEED_ROOT = PROJECT_ROOT / "tests" / "fixtures" / "seed9004"


EXPECTED_IDS = [
    "quotation_workflow_1",
    "quotation_workflow_1_ja",
    "lab_sample_flow",
]


def test_catalog_ids_and_order_are_explicit_and_deterministic() -> None:
    first = list_scenarios()
    second = list_scenarios()

    assert [scenario.id for scenario in first] == EXPECTED_IDS
    assert [scenario.id for scenario in second] == EXPECTED_IDS
    assert first is not second
    assert all(left is not right for left, right in zip(first, second, strict=True))


def test_unknown_scenario_id_has_explicit_behavior() -> None:
    with pytest.raises(UnknownScenarioError, match="supported IDs") as error:
        get_scenario("quotation_workflow_1_ja_extra")

    assert error.value.scenario_id == "quotation_workflow_1_ja_extra"
    assert error.value.supported_ids == tuple(EXPECTED_IDS)


def test_every_catalog_truth_is_canonical() -> None:
    for scenario in list_scenarios():
        validate_canonical_graph(scenario.truth)
        assert scenario.truth.is_valid
        assert scenario.truth.source_node_id in scenario.truth.nodes
        assert scenario.truth.sink_node_id in scenario.truth.nodes


def test_quotation_locales_share_the_same_canonical_truth() -> None:
    en = get_scenario("quotation_workflow_1")
    ja = get_scenario("quotation_workflow_1_ja")

    assert en.canonical_scenario_id == "quotation_workflow_1"
    assert ja.canonical_scenario_id == "quotation_workflow_1"
    assert en.locale == "en"
    assert ja.locale == "ja"
    assert en.truth == ja.truth
    assert en.truth.model_dump(mode="json") == ja.truth.model_dump(mode="json")


def test_quotation_truth_matches_the_phase3_truth_fixture() -> None:
    fixture = BusinessProcessGraph.model_validate_json(
        (SEED_ROOT / "truth.json").read_text(encoding="utf-8")
    )
    catalog_truth = get_scenario("quotation_workflow_1").truth

    assert catalog_truth == fixture
    assert catalog_truth.model_dump(mode="json") == fixture.model_dump(mode="json")


def test_quotation_business_addresses_and_boundaries_are_preserved() -> None:
    truth = get_scenario("quotation_workflow_1").truth

    assert set(business_node_ids(truth)) == {"r", "cc", "cq", "ap", "sq", "me"}
    assert set(business_edge_ids(truth)) == {"e1", "e2", "e3", "e4", "e5", "e6"}
    assert sum(concept.kind != "rationale" for concept in truth.concepts.values()) == 22
    assert business_entry_node_ids(truth) == ("r",)
    assert set(business_exit_node_ids(truth)) == {"sq", "me"}
    assert truth.source_node_id not in business_node_ids(truth)
    assert truth.sink_node_id not in business_node_ids(truth)


def test_lab_sample_flow_is_not_quotation_data() -> None:
    truth = get_scenario("lab_sample_flow").truth

    assert truth.id == "lab"
    assert set(business_node_ids(truth)) == {"n1", "n2", "n3", "n4"}
    assert set(business_edge_ids(truth)) == {"l1", "l2", "l3"}
    assert "tc_activity_receive_request" not in truth.concepts
    assert "tc_system_quoting" not in truth.concepts
    assert all(
        "quotation" not in concept.description.lower()
        for concept in truth.concepts.values()
    )


def test_prompt_metadata_preserves_english_and_japanese_task_content() -> None:
    en = get_scenario("quotation_workflow_1")
    ja = get_scenario("quotation_workflow_1_ja")

    assert en.prompt.persona == (
        "You are a sales employee who has worked at the company for a few years. "
        "You are friendly, cooperative, and pragmatic. You answer questions plainly "
        "and truthfully in everyday business language. You are not familiar with "
        "business-analysis terminology and you never speculate or make things up."
    )
    assert en.prompt.reason_for_call == (
        "You have been asked to take part in a short interview about how quotations "
        "are prepared in your team."
    )
    assert (
        "Answer the interviewer's questions truthfully" in en.prompt.task_instructions
    )
    assert "あなたは数年間この会社で働いている営業担当者です。" in ja.prompt.persona
    assert "チームで見積書がどのように作成されているか" in ja.prompt.reason_for_call
    assert "インタビュアーの質問に" in ja.prompt.task_instructions
    assert en.prompt != ja.prompt


def test_initial_messages_preserve_role_order_and_locale_content() -> None:
    en = get_scenario("quotation_workflow_1")
    ja = get_scenario("quotation_workflow_1_ja")

    assert [(message.role, message.content) for message in en.initial_messages] == [
        (
            "assistant",
            "Hello, I'm a business analyst and I'd like to interview you about how "
            "your team prepares quotations. Is now a good time?",
        ),
        ("user", "Sure, that's fine. What would you like to know?"),
    ]
    assert [(message.role, message.content) for message in ja.initial_messages] == [
        (
            "assistant",
            "お世話になっております。私はビジネスアナリストの田中と申します。"
            "御社のチームでの見積書の作成プロセスについてお話を伺いたいのですが、"
            "今よろしいでしょうか？",
        ),
        ("user", "はい、大丈夫です。何を知りたいですか？"),
    ]


def test_get_scenario_returns_no_mutable_shared_singleton() -> None:
    first = get_scenario("quotation_workflow_1")
    second = get_scenario("quotation_workflow_1")

    assert first is not second
    assert first.truth is not second.truth
    first.truth.nodes.pop("r")
    assert "r" in second.truth.nodes
    assert first.initial_messages is not second.initial_messages


def test_catalog_runtime_resources_omit_task_wrapper_and_private_knowledge() -> None:
    catalog_text = (
        PROJECT_ROOT
        / "src"
        / "business_interview"
        / "scenarios"
        / "data"
        / "catalog.json"
    ).read_text(encoding="utf-8")

    for omitted in (
        "env_assertions",
        "reward_basis",
        "known_info",
        "unknown_info",
        "env_type",
        "func_name",
        "skn_",
        "ske_",
        "skc_",
    ):
        assert omitted not in catalog_text


def test_catalog_truth_connects_directly_to_the_existing_primary_evaluator() -> None:
    agent = AgentGraph.model_validate_json(
        (SEED_ROOT / "agent.json").read_text(encoding="utf-8")
    )
    context = InterviewEvaluationContext.model_validate_json(
        (SEED_ROOT / "evaluation_context.json").read_text(encoding="utf-8")
    )
    knowledge = KnowledgeCoverageView.model_validate_json(
        (SEED_ROOT / "knowledge_coverage.json").read_text(encoding="utf-8")
    )
    expected = json.loads((SEED_ROOT / "expected.json").read_text(encoding="utf-8"))[
        "oracle"
    ]["fields"]

    actual = asdict(
        evaluate_primary(
            agent,
            get_scenario("quotation_workflow_1").truth,
            context,
            knowledge,
        )
    )

    assert actual == expected
