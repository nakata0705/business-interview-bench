"""Phase 21 policy and availability-aware artifact contracts."""

# pyright: reportMissingImports=false

from __future__ import annotations

import json
from pathlib import Path

import business_interview_bench.phase14 as phase14
from business_interview_bench.phase14 import load_experiment_config

_ROOT = Path(__file__).parents[1]


def test_phase21_calibration_manifest_uses_the_provisional_candidate_policy() -> None:
    config = load_experiment_config(_ROOT / "experiments/phase21/calibration.json")

    assert [run.scenario_id for run in config.runs] == [
        "lab_sample_flow",
        "quotation_workflow_1",
        "quotation_workflow_1_ja",
    ]
    assert [run.run_index for run in config.runs] == [0, 1, 2]
    assert all(run.candidate_max_tokens == 2048 for run in config.runs)
    assert all(
        run.candidate_generation["reasoning_effort"] == "low" for run in config.runs
    )
    assert all(
        run.stakeholder_generation["reasoning_effort"] == "low" for run in config.runs
    )
    assert all(run.candidate_generation["max_retries"] == 0 for run in config.runs)


def test_phase21_aggregate_excludes_non_terminal_runs() -> None:
    aggregate = phase14.aggregate_run_summaries(
        [
            {"availability": "unavailable", "run": {}},
            {"availability": "available", "run": {}},
        ]
    )

    assert aggregate["manifest_run_count"] == 2
    assert aggregate["available_run_count"] == 1
    assert aggregate["unavailable_run_count"] == 1
    assert aggregate["run_count"] == 1
    assert aggregate["completion_rate"] is None


def test_phase21_safe_artifacts_do_not_score_unavailable_runs_as_zero() -> None:
    policy = json.loads(
        (_ROOT / "experiments/phase21/generation-policy-experiment.json").read_text(
            encoding="utf-8"
        )
    )
    calibration = json.loads(
        (_ROOT / "experiments/phase21/real-calibration-summary.json").read_text(
            encoding="utf-8"
        )
    )
    manifest_text = (_ROOT / "experiments/phase21/calibration.json").read_text(
        encoding="utf-8"
    )

    assert len(policy["arms"]) == 3
    assert [arm["run_index"] for arm in policy["arms"]] == [400, 401, 402]
    assert policy["common_controls"]["candidate_generation_seed"] is None
    assert policy["common_controls"]["candidate_generation_seed_controlled"] is False
    assert all(arm["candidate_generation"]["seed"] is None for arm in policy["arms"])
    assert policy["decision"]["provisional_policy"] == "expanded_2048_low_reasoning"
    assert all(arm["primary_evaluation_field_count"] == 41 for arm in policy["arms"])
    assert calibration["aggregate"] == {
        "total_manifest_runs": 3,
        "available_run_count": 1,
        "unavailable_run_count": 2,
        "scored_run_count": 1,
        "available_completion_rate": 1.0,
        "available_accepted_nonempty_plan_response_count": 1,
        "available_accepted_annotated_response_count": 1,
        "unavailable_runs_excluded_from_aggregates": True,
    }
    assert all(
        run["availability"] == "unavailable" for run in calibration["unavailable_runs"]
    )
    assert all(
        run["partial_observation"]["not_scored"]
        for run in calibration["unavailable_runs"]
    )
    assert calibration["primary_evaluation_field_count_contract"] == 41
    records = calibration["runs"][0]["candidate_generation_records"]
    assert records
    assert all(record["configured_max_tokens"] == 2048 for record in records)
    assert all("outcome_kind" in record for record in records)
    assert all("tool_names" in record for record in records)

    for payload in (policy, calibration, json.loads(manifest_text)):
        serialized = json.dumps(payload, ensure_ascii=False)
        assert "stakeholder_knowledge" not in serialized
        assert "skn_" not in serialized
        assert "skc_" not in serialized
        assert "reasoning_details" not in serialized
