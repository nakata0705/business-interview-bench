"""Phase 17 reasoning-effort configuration and safe-summary tests."""

# The workspace-level auxiliary resolver may not see Inspect's dev group.
# Project-level ``uv run pyright`` is authoritative for this package.
# pyright: reportMissingImports=false

from __future__ import annotations

import json
from collections.abc import Mapping
from types import SimpleNamespace
from typing import Any, cast

import pytest
from inspect_ai._cli.eval import RunConfigInput
from inspect_ai.model import GenerateConfig

import business_interview_bench.phase14 as phase14
from business_interview_bench.phase14 import (
    build_inspect_run_config,
    load_experiment_config,
)


class ModelEvent:
    def __init__(
        self,
        *,
        role: str | None,
        completion: str,
        usage: Mapping[str, int | float],
        input_text: str,
    ) -> None:
        self.role = role
        self.model = "shared/model"
        self.input = [SimpleNamespace(text=input_text)]
        self.output = SimpleNamespace(completion=completion, usage=usage)


def _sample() -> SimpleNamespace:
    observation = {
        "id": "obs-private",
        "turn": 1,
        "text": "PRIVATE-STAKEHOLDER-KNOWLEDGE",
    }
    runtime = {
        "scenario_id": "lab_sample_flow",
        "protocol_state": {"status": "completed", "failure_reason": None},
        "observations": [observation],
        "initial_observation_count": 0,
        "semantic_ledger": {
            "entries": [
                {
                    "observation_id": observation["id"],
                    "public_message_turn": 1,
                    "plan": {"items": []},
                    "annotations": [],
                }
            ]
        },
        "candidate_turns": 1,
        "candidate_steps": 1,
        "stakeholder_turns": 1,
        "question_count": 1,
        "max_interview_turns": 1,
        "max_candidate_steps_per_turn": 8,
        "candidate_max_tokens": 1024,
    }
    events = [
        ModelEvent(
            role=None,
            completion="PRIVATE-CANDIDATE-COMPLETION",
            usage={
                "input_tokens": 5,
                "output_tokens": 2,
                "reasoning_tokens": 1,
                "total_tokens": 7,
            },
            input_text="",
        ),
        ModelEvent(
            role="stakeholder",
            completion='{"items": []}',
            usage={
                "input_tokens": 10,
                "output_tokens": 2,
                "reasoning_tokens": 1,
                "total_tokens": 12,
            },
            input_text=phase14._PLAN_PROMPT_MARKER,
        ),
        ModelEvent(
            role="stakeholder",
            completion='{"message": "PRIVATE-PUBLIC-COMPLETION"}',
            usage={
                "input_tokens": 10,
                "output_tokens": 3,
                "reasoning_tokens": 3,
                "total_tokens": 13,
            },
            input_text=phase14._REALIZATION_PROMPT_MARKER,
        ),
    ]
    return SimpleNamespace(
        events=events,
        store={
            "BusinessInterviewLiveStore:live_state": runtime,
            "BusinessInterviewLiveStore:stakeholder_profile": {
                "stakeholder_id": "phase17-safe-profile",
                "stakeholder_knowledge": "PRIVATE-KNOWLEDGE-MUST-NOT-LEAK",
            },
            "BusinessInterviewLiveStore:stakeholder_seed": 1401,
        },
        metadata={},
        epoch=1,
        scores={},
        model_usage={
            "shared/model": {
                "input_tokens": 25,
                "output_tokens": 7,
                "reasoning_tokens": 5,
                "total_tokens": 32,
            }
        },
        role_usage={
            "stakeholder": {
                "input_tokens": 20,
                "output_tokens": 5,
                "reasoning_tokens": 4,
                "total_tokens": 25,
            }
        },
    )


def _log(
    sample: SimpleNamespace,
    *,
    reasoning_effort: str,
    metadata: dict[str, Any] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        eval=SimpleNamespace(
            model="shared/model",
            model_roles={
                "stakeholder": {
                    "model": "shared/model",
                    "config": {
                        "temperature": 0.0,
                        "reasoning_effort": reasoning_effort,
                    },
                }
            },
            eval_id="eval-phase17",
            run_id="run-phase17",
            task_registry_name="business_interview_bench/phase13_interview",
            task_args_passed={"candidate_max_tokens": 1024},
            model_generate_config={"temperature": 0.0},
        ),
        metadata=metadata or {},
        plan=None,
        samples=[sample],
        status="success",
    )


def test_phase17_manifest_is_three_one_turn_policy_runs() -> None:
    config = load_experiment_config("experiments/phase17/calibration.json")
    assert len(config.runs) == 3
    assert [run.stakeholder_generation["reasoning_effort"] for run in config.runs] == [
        "none",
        "minimal",
        "low",
    ]
    for run in config.runs:
        assert run.candidate_model == "openrouter/deepseek/deepseek-v4-flash-0731"
        assert run.stakeholder_model == "openrouter/deepseek/deepseek-v4-flash-0731"
        assert run.scenario_id == "lab_sample_flow"
        assert run.stakeholder_profile.stakeholder_id == "phase14-lab-technician"
        assert run.stakeholder_seed == 1401
        assert run.max_interview_turns == 1
        assert run.max_candidate_steps_per_turn == 8
        assert run.candidate_max_tokens == 1024
        assert run.candidate_generation == {"temperature": 0.0}
        assert "max_tokens" not in run.stakeholder_generation


def test_reasoning_effort_is_isolated_to_stakeholder_run_config() -> None:
    config = load_experiment_config("experiments/phase17/calibration.json")
    rendered = [build_inspect_run_config(run) for run in config.runs]

    assert [item["generate_config"] for item in rendered] == [
        {"temperature": 0.0},
        {"temperature": 0.0},
        {"temperature": 0.0},
    ]
    assert [
        item["model_roles"]["stakeholder"]["config"]["reasoning_effort"]
        for item in rendered
    ] == ["none", "minimal", "low"]
    assert all(
        "max_tokens" not in item["model_roles"]["stakeholder"]["config"]
        for item in rendered
    )
    for item in rendered:
        parsed = RunConfigInput.model_validate(item)
        assert parsed.model_roles["stakeholder"].config.reasoning_effort in {
            "none",
            "minimal",
            "low",
        }


def test_generate_config_rejects_unsupported_reasoning_effort() -> None:
    with pytest.raises(ValueError):
        GenerateConfig.model_validate({"reasoning_effort": "unsupported"})

    config = load_experiment_config("experiments/phase17/calibration.json")
    invalid_run = config.runs[0].model_copy(
        update={"stakeholder_generation": {"reasoning_effort": "unsupported"}}
    )
    with pytest.raises(ValueError, match="stakeholder_generation"):
        build_inspect_run_config(invalid_run)


def test_requested_effort_and_measured_usage_are_separate_and_private() -> None:
    sample = _sample()
    summary = phase14.summarize_eval_log_object(
        cast(Any, _log(sample, reasoning_effort="minimal"))
    )
    run = summary["runs"][0]

    assert summary["schema_version"] == 3
    assert run["run"]["requested_reasoning_effort"] == "minimal"
    assert run["usage"]["candidate"]["reasoning_tokens"] == 1
    assert run["usage"]["stakeholder"]["reasoning_tokens"] == 4
    assert run["usage"]["stakeholder"]["output_tokens"] == 5
    assert run["run"]["reasoning_capability_metadata"]["available"] is False
    assert all(
        item["requested_reasoning_effort"] == "minimal"
        for item in run["generation_usage"]["stakeholder"]
    )
    assert all(
        item["requested_reasoning_effort"] is None
        for item in run["generation_usage"]["candidate"]
    )
    assert all(
        {
            "phase",
            "attempt_index",
            "retry",
            "accepted",
            "input_tokens",
            "output_tokens",
            "reasoning_tokens",
            "non_reasoning_output_tokens",
            "total_tokens",
            "reasoning_share",
            "visible_completion_chars",
            "requested_reasoning_effort",
        }.issubset(item)
        for item in run["generation_usage"]["stakeholder"]
    )

    serialized = json.dumps(summary, ensure_ascii=False, sort_keys=True)
    for private_value in (
        "PRIVATE-CANDIDATE-COMPLETION",
        "PRIVATE-PUBLIC-COMPLETION",
        "PRIVATE-STAKEHOLDER-KNOWLEDGE",
        "PRIVATE-KNOWLEDGE-MUST-NOT-LEAK",
        "obs-private",
    ):
        assert private_value not in serialized


def test_explicit_capability_metadata_is_whitelisted_without_inference() -> None:
    metadata = {
        "reasoning_enabled": True,
        "default_reasoning_effort": "minimal",
        "supported_reasoning_efforts": ["none", "minimal", "low"],
        "private_provider_payload": "DO-NOT-PERSIST",
    }
    summary = phase14.summarize_eval_log_object(
        cast(Any, _log(_sample(), reasoning_effort="low", metadata=metadata))
    )
    capability = summary["runs"][0]["run"]["reasoning_capability_metadata"]
    assert capability == {
        "available": True,
        "documented_default_effort": "minimal",
        "reasoning_supported": True,
        "source": "Inspect eval/model metadata",
        "supported_efforts": ["none", "minimal", "low"],
    }
    assert "DO-NOT-PERSIST" not in json.dumps(summary)
