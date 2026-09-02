"""Phase 18 low-reasoning calibration manifest and safe-summary tests."""

# The workspace-level auxiliary resolver may not see Inspect's dev group.
# Project-level ``uv run pyright`` is authoritative for this package.
# pyright: reportMissingImports=false

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from inspect_ai._cli.eval import RunConfigInput

import business_interview_bench.phase14 as phase14
from business_interview_bench.phase14 import (
    build_inspect_run_config,
    load_experiment_config,
)

_MODEL = "openrouter/deepseek/deepseek-v4-flash-0731"


def test_phase18_manifest_has_exact_three_low_reasoning_runs() -> None:
    config = load_experiment_config("experiments/phase18/calibration.json")

    assert len(config.runs) == 3
    assert [run.run_index for run in config.runs] == [0, 1, 2]
    assert [run.scenario_id for run in config.runs] == [
        "lab_sample_flow",
        "quotation_workflow_1",
        "quotation_workflow_1_ja",
    ]
    assert [run.stakeholder_profile.stakeholder_id for run in config.runs] == [
        "phase14-lab-technician",
        "phase14-sales-owner",
        "phase14-sales-owner-ja",
    ]
    assert [run.stakeholder_seed for run in config.runs] == [1401, 1402, 1403]

    for run in config.runs:
        assert run.candidate_model == _MODEL
        assert run.stakeholder_model == _MODEL
        assert run.max_interview_turns == 8
        assert run.max_candidate_steps_per_turn == 8
        assert run.candidate_max_tokens == 1024
        assert run.candidate_generation == {"temperature": 0.0}
        assert run.stakeholder_generation == {
            "temperature": 0.0,
            "reasoning_effort": "low",
        }
        assert "max_tokens" not in run.stakeholder_generation
        assert run.epoch == 1


def test_phase18_rendered_configs_pass_inspect_schema_without_candidate_policy_leak() -> (
    None
):
    config = load_experiment_config("experiments/phase18/calibration.json")

    for run in config.runs:
        rendered = build_inspect_run_config(run)
        parsed = RunConfigInput.model_validate(rendered)

        model_entry = cast(Any, parsed.model)
        assert model_entry.model == _MODEL
        stakeholder_role = cast(Any, parsed.model_roles["stakeholder"])
        assert stakeholder_role.model == _MODEL
        assert parsed.generate_config.temperature == 0.0
        assert parsed.generate_config.reasoning_effort is None
        assert stakeholder_role.config.temperature == 0.0
        assert stakeholder_role.config.reasoning_effort == "low"
        assert "reasoning_effort" not in rendered["generate_config"]
        assert "max_tokens" not in rendered["model_roles"]["stakeholder"]["config"]
        assert rendered["task"]["args"]["candidate_max_tokens"] == 1024
        assert rendered["eval_config"] == {"epochs": 1}


def test_phase18_committed_summary_has_three_safe_low_runs() -> None:
    summary = json.loads(
        Path("experiments/phase18/real-calibration-summary.json").read_text(
            encoding="utf-8"
        )
    )

    assert summary["schema_version"] == 3
    assert len(summary["runs"]) == 3
    assert [run["run"]["requested_reasoning_effort"] for run in summary["runs"]] == [
        "low",
        "low",
        "low",
    ]
    assert summary["phase18"]["structured_response"]["valid_what_count"] == 3
    assert summary["phase18"]["structured_response"]["valid_how_count"] == 0
    assert all(run["primary_evaluation"] == {} for run in summary["runs"])

    serialized = json.dumps(summary, ensure_ascii=False, sort_keys=True)
    for private_marker in (
        "PRIVATE-TRANSCRIPT",
        "PRIVATE-KNOWLEDGE",
        "stakeholder_knowledge",
        "skn_",
    ):
        assert private_marker not in serialized


def _safe_summary_log() -> SimpleNamespace:
    runtime = {
        "scenario_id": "lab_sample_flow",
        "protocol_state": {
            "status": "incomplete",
            "failure_reason": "max_turns_exhausted",
        },
        "observations": [
            {"id": "obs-private", "turn": 1, "text": "PRIVATE-TRANSCRIPT"}
        ],
        "initial_observation_count": 0,
        "semantic_ledger": {"entries": []},
        "candidate_turns": 1,
        "candidate_steps": 1,
        "stakeholder_turns": 0,
        "question_count": 1,
        "max_interview_turns": 8,
        "max_candidate_steps_per_turn": 8,
        "candidate_max_tokens": 1024,
    }
    sample = SimpleNamespace(
        events=[],
        store={
            "BusinessInterviewLiveStore:live_state": runtime,
            "BusinessInterviewLiveStore:stakeholder_profile": {
                "stakeholder_id": "phase14-lab-technician",
                "stakeholder_knowledge": "PRIVATE-KNOWLEDGE",
            },
            "BusinessInterviewLiveStore:stakeholder_seed": 1401,
        },
        metadata={},
        epoch=1,
        scores={},
        model_usage={},
        role_usage={},
    )
    return SimpleNamespace(
        eval=SimpleNamespace(
            model=_MODEL,
            model_roles={
                "stakeholder": {
                    "model": _MODEL,
                    "config": {"temperature": 0.0, "reasoning_effort": "low"},
                }
            },
            eval_id="eval-phase18",
            run_id="run-phase18",
            task_registry_name="business_interview_bench/phase13_interview",
            task_args_passed={
                "scenario_id": "lab_sample_flow",
                "max_interview_turns": 8,
                "max_candidate_steps_per_turn": 8,
                "candidate_max_tokens": 1024,
                "run_index": 0,
            },
            model_generate_config={"temperature": 0.0},
        ),
        metadata={},
        plan=None,
        samples=[sample],
        status="success",
    )


def test_phase18_safe_summary_records_low_without_private_content() -> None:
    summary = phase14.summarize_eval_log_object(
        cast(Any, _safe_summary_log()), source_name="phase18.eval"
    )
    run = summary["runs"][0]

    assert run["run"]["requested_reasoning_effort"] == "low"
    assert run["run"]["generation_parameters"] == {
        "candidate": {"temperature": 0.0},
        "stakeholder": {"temperature": 0.0, "reasoning_effort": "low"},
    }
    assert run["protocol"]["failure_reason"] == "max_turns_exhausted"

    serialized = json.dumps(summary, ensure_ascii=False, sort_keys=True)
    assert "PRIVATE-TRANSCRIPT" not in serialized
    assert "PRIVATE-KNOWLEDGE" not in serialized
    assert "stakeholder_knowledge" not in serialized
    assert "obs-private" not in serialized
    assert "requested_reasoning_effort" in serialized
