"""Phase 20 semantic-contract calibration manifest and safe-artifact tests."""

# The workspace-level auxiliary resolver may not see Inspect's dev group.
# Project-level ``uv run pyright`` is authoritative for this package.
# pyright: reportMissingImports=false

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from inspect_ai._cli.eval import RunConfigInput

from business_interview_bench.phase14 import (
    build_inspect_run_config,
    load_experiment_config,
)

_MODEL = "openrouter/deepseek/deepseek-v4-flash-0731"


def test_phase20_manifest_has_exact_three_protocol_runs() -> None:
    config = load_experiment_config("experiments/phase20/calibration.json")

    assert len(config.runs) == 3
    assert [run.run_index for run in config.runs] == [0, 1, 2]
    assert [run.scenario_id for run in config.runs] == [
        "lab_sample_flow",
        "quotation_workflow_1",
        "quotation_workflow_1_ja",
    ]

    for run in config.runs:
        assert run.candidate_model == _MODEL
        assert run.stakeholder_model == _MODEL
        assert run.candidate_generation == {"temperature": 0.0}
        assert run.stakeholder_generation == {
            "temperature": 0.0,
            "reasoning_effort": "low",
        }
        assert "max_tokens" not in run.stakeholder_generation
        assert run.candidate_max_tokens == 1024
        assert run.max_interview_turns == 8
        assert run.max_candidate_steps_per_turn == 8
        assert run.epoch == 1


def test_phase20_rendered_configs_keep_reasoning_policy_on_stakeholder_only() -> None:
    config = load_experiment_config("experiments/phase20/calibration.json")

    for run in config.runs:
        rendered = build_inspect_run_config(run)
        parsed = RunConfigInput.model_validate(rendered)

        model_entry = cast(Any, parsed.model)
        stakeholder_role = cast(Any, parsed.model_roles["stakeholder"])
        assert model_entry.model == _MODEL
        assert stakeholder_role.model == _MODEL
        assert parsed.generate_config.reasoning_effort is None
        assert stakeholder_role.config.reasoning_effort == "low"
        assert "reasoning_effort" not in rendered["generate_config"]
        assert "max_tokens" not in rendered["model_roles"]["stakeholder"]["config"]


def test_phase20_safe_artifact_records_nonempty_annotated_successes() -> None:
    summary = json.loads(
        Path("experiments/phase20/real-calibration-summary.json").read_text(
            encoding="utf-8"
        )
    )
    preflight = json.loads(
        Path("experiments/phase20/preflight.json").read_text(encoding="utf-8")
    )

    assert summary["phase"] == 20
    assert summary["calibration_status"] == "partial"
    assert summary["protocol"]["requested_scenario_count"] == 3
    assert summary["protocol"]["observed_scenario_count"] == 2
    assert len(summary["runs"]) == 2
    assert len(summary["unavailable_runs"]) == 1
    assert summary["structured_output"]["provider_request_format"] == "json_schema"
    assert summary["structured_output"]["schema_strict"] is False
    assert summary["analysis"]["observed_primary_evaluation_count"] == 2
    assert summary["analysis"]["observed_primary_evaluation_field_count"] == 41
    assert summary["analysis"]["observed_nonempty_what_count"] == 3
    assert summary["analysis"]["observed_annotated_how_count"] == 3
    assert summary["aggregate"]["total_accepted_nonempty_plan_response_count"] == 3
    assert summary["aggregate"]["total_accepted_annotated_response_count"] == 3
    assert summary["aggregate"]["total_stakeholder_what_semantic_rejection_count"] == 0
    assert summary["aggregate"]["total_stakeholder_how_semantic_rejection_count"] == 0
    assert summary["aggregate"]["total_stakeholder_provider_error_count"] == 0

    assert preflight["status"] == "success"
    assert preflight["accepted_public_response_count"] == 1
    assert preflight["accepted_nonempty_plan_response_count"] == 1
    assert preflight["accepted_annotated_response_count"] == 1
    assert preflight["what_semantic_rejection_count"] == 0
    assert preflight["how_semantic_rejection_count"] == 0

    for run in summary["runs"]:
        assert run["run"]["requested_reasoning_effort"] == "low"
        assert len(run["primary_evaluation"]) == 41
        assert run["diagnostics"]["accepted_nonempty_plan_response_count"] >= 1
        assert run["diagnostics"]["accepted_annotated_response_count"] >= 1
        assert run["diagnostics"]["stakeholder_structured_output_modes"] == [
            "inspect_response_schema"
        ]

    serialized = json.dumps(
        {"summary": summary, "preflight": preflight},
        ensure_ascii=False,
        sort_keys=True,
    )
    for private_marker in (
        "PRIVATE-TRANSCRIPT",
        "PRIVATE-KNOWLEDGE",
        "stakeholder_knowledge",
        "skn_",
        "reasoning_content",
    ):
        assert private_marker not in serialized
