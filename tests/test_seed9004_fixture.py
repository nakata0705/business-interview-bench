"""Offline contract tests for the curated seed 9004 parity fixture."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from business_interview.models import (
    STRUCTURAL_SINK_ID,
    STRUCTURAL_SOURCE_ID,
    AbsentType,
    AgentGraph,
    BusinessProcessGraph,
    ConceptRef,
    DontKnowType,
    UnsetType,
    business_edge_ids,
    business_entry_node_ids,
    business_exit_node_ids,
    business_node_ids,
    canonicalize_truth_graph,
    validate_canonical_graph,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = PROJECT_ROOT / "tests" / "fixtures" / "seed9004"
NORMALIZED_FILES = ("truth.json", "agent.json", "expected.json")
SOURCE_COMMIT = "00a98a5efbe9db2ccc3aaf2f04529ef50c323bb0"


def _load(name: str) -> dict[str, Any]:
    value = json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _stable_json(value: Any) -> str:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    )


def _reverse_mappings(value: Any) -> None:
    if not isinstance(value, dict):
        return
    for key in ("concepts", "nodes", "edges"):
        child = value.get(key)
        if isinstance(child, dict):
            value[key] = dict(reversed(list(child.items())))


def test_seed9004_truth_loads_as_canonical_truth_graph() -> None:
    truth = BusinessProcessGraph.model_validate(_load("truth.json"))

    validate_canonical_graph(truth)
    assert truth.is_valid
    assert truth.source_node_id == STRUCTURAL_SOURCE_ID
    assert truth.sink_node_id == STRUCTURAL_SINK_ID
    assert business_node_ids(truth) == ["ap", "cc", "cq", "me", "r", "sq"]
    assert business_edge_ids(truth) == ["e1", "e2", "e3", "e4", "e5", "e6"]
    assert business_entry_node_ids(truth) == ("r",)
    assert business_exit_node_ids(truth) == ("me", "sq")


def test_seed9004_agent_preserves_saved_four_state_slots() -> None:
    agent = AgentGraph.model_validate(_load("agent.json"))

    assert agent.is_valid
    assert agent.start_node_ids == ["node_receive_request"]
    assert agent.end_node_ids == [
        "node_send_quotation_customer",
        "node_send_month_end_summary",
    ]
    assert isinstance(
        agent.nodes["node_check_customer_info"].necessity_rationale,
        DontKnowType,
    )
    assert isinstance(agent.nodes["node_receive_request"].system, UnsetType)
    assert isinstance(
        agent.edges["edge_receive_to_check"].condition,
        AbsentType,
    )
    assert isinstance(
        agent.nodes["node_approve_high_value"].necessity_rationale,
        ConceptRef,
    )


def test_seed9004_agent_dump_reload_has_semantic_equality() -> None:
    agent = AgentGraph.model_validate(_load("agent.json"))
    restored = AgentGraph.model_validate(agent.model_dump(mode="json"))

    assert restored == agent
    assert restored.is_valid


def test_fixture_provenance_identifies_seed_and_source() -> None:
    provenance = _load("provenance.json")

    assert provenance["schema_version"] == (
        "business_interview.phase3.normalized_fixture.v1"
    )
    assert provenance["seed"] == 9004
    assert provenance["task_id"] == "quotation_workflow_1"
    assert provenance["source_repository"] == "nakata0705/tau2-bench"
    assert provenance["source_branch"] == "business-interview"
    assert provenance["source_commit_sha"] == SOURCE_COMMIT
    assert provenance["generation_method"] == (
        "migration/scripts/build_seed9004_fixture.py"
    )
    assert provenance["fixture"]["seed"] == 9004
    assert provenance["fixture"]["task_id"] == "quotation_workflow_1"
    assert provenance["source"]["repository"] == "nakata0705/tau2-bench"
    assert provenance["source"]["branch"] == "business-interview"
    assert provenance["source"]["commit_sha"] == SOURCE_COMMIT
    assert provenance["source"]["working_tree_clean"] is True
    assert {item["path"] for item in provenance["source"]["artifacts"]} == {
        "artifacts/business_interview_real_llm/run_00_seed9004.json",
        "artifacts/business_interview_real_llm/run_00_seed9004.private.json",
        "artifacts/business_interview_real_llm/run_00_seed9004.diagnostics.json",
    }
    datetime.fromisoformat(
        provenance["generation"]["generated_at"].replace("Z", "+00:00")
    )


def test_expected_contains_only_primary_recomputed_oracle_fields() -> None:
    expected = _load("expected.json")

    assert expected["schema_version"] == ("business_interview.phase3.primary_oracle.v1")
    assert expected["seed"] == 9004
    assert expected["task_id"] == "quotation_workflow_1"
    assert expected["scope"] == "primary_agent_to_truth"
    assert expected["legacy_stored_comparison"]["status"] == "matched"
    assert expected["legacy_stored_comparison"]["differences"] == []
    assert (
        expected["oracle"]["fields"] == expected["legacy_stored_comparison"]["fields"]
    )
    assert "stakeholder_truth_reference" not in json.dumps(expected)
    assert "llm_call_metrics" not in json.dumps(expected)


def test_normalized_files_have_no_serialized_python_class_paths() -> None:
    class_path_key = re.compile(
        r'"(?:__class__|__type__|class_path|python_class|python_path)"\s*:'
    )
    class_path_value = re.compile(r"(?<!_)\btau2(?:\.[A-Za-z_][\w]*)+")

    for name in NORMALIZED_FILES:
        text = (FIXTURE_ROOT / name).read_text(encoding="utf-8")
        assert class_path_key.search(text) is None
        assert class_path_value.search(text) is None


def test_fixture_json_and_truth_canonicalization_are_deterministic() -> None:
    truth_text = (FIXTURE_ROOT / "truth.json").read_text(encoding="utf-8")
    agent_text = (FIXTURE_ROOT / "agent.json").read_text(encoding="utf-8")
    truth = BusinessProcessGraph.model_validate_json(truth_text)
    agent = AgentGraph.model_validate_json(agent_text)

    assert truth_text == _stable_json(truth.model_dump(mode="json"))
    assert agent_text == _stable_json(agent.model_dump(mode="json"))

    reordered_truth_payload = truth.model_dump(mode="json")
    _reverse_mappings(reordered_truth_payload)
    reordered_truth = BusinessProcessGraph.model_validate(reordered_truth_payload)
    canonical_reordered = canonicalize_truth_graph(reordered_truth)
    assert _stable_json(canonical_reordered.model_dump(mode="json")) == truth_text

    reordered_agent_payload = agent.model_dump(mode="json")
    _reverse_mappings(reordered_agent_payload)
    reordered_agent = AgentGraph.model_validate(reordered_agent_payload)
    assert _stable_json(reordered_agent.model_dump(mode="json")) == agent_text


def test_provenance_digests_cover_deterministic_fixture_files() -> None:
    provenance = _load("provenance.json")
    digests = provenance["fixture"]["deterministic_file_sha256"]

    for name in NORMALIZED_FILES:
        actual = hashlib.sha256((FIXTURE_ROOT / name).read_bytes()).hexdigest()
        assert digests[name] == actual


def test_target_source_tree_has_no_tau2_imports() -> None:
    import_pattern = re.compile(r"(?:^|\s)(?:from|import)\s+tau2(?:\s|\.|$)")

    for path in (PROJECT_ROOT / "src").rglob("*.py"):
        assert import_pattern.search(path.read_text(encoding="utf-8")) is None
