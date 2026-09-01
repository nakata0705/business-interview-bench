"""Phase 14 .eval summary and calibration-harness tests."""

# The workspace-level auxiliary resolver may not see Inspect's dev group.
# Project-level ``uv run pyright`` is authoritative for this package.
# pyright: reportMissingImports=false

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from inspect_ai import eval as inspect_eval
from inspect_ai._cli.eval import RunConfigInput, parse_run_config
from inspect_ai.log import read_eval_log
from inspect_ai.model import ModelOutput, get_model

import business_interview_bench.phase14 as phase14
from business_interview.scenarios import get_scenario
from business_interview.stakeholders import StakeholderProfile
from business_interview_bench.inspect_adapter.multiturn import (
    phase13_interview_task,
    phase13_smoke_interview_task,
)
from business_interview_bench.phase14 import (
    build_inspect_run_config,
    build_inspect_task_config,
    load_experiment_config,
    summarize_eval_log,
    summarize_eval_log_object,
    summarize_eval_logs,
)


def _profile() -> StakeholderProfile:
    truth = get_scenario("lab_sample_flow").truth
    node_ids = tuple(
        node_id for node_id, node in truth.nodes.items() if not node.is_structural
    )
    edge_ids = tuple(
        edge_id for edge_id, edge in truth.edges.items() if not edge.is_structural
    )
    return StakeholderProfile(
        stakeholder_id="phase14-test-profile",
        name="Phase 14 test profile",
        role="lab technician",
        visible_node_ids=node_ids,
        visible_edge_ids=edge_ids,
        visible_node_attributes={node_id: ("activity",) for node_id in node_ids},
        visible_edge_attributes={edge_id: ("condition",) for edge_id in edge_ids},
    )


def _stakeholder_outputs(message: str = "Answer.") -> list[ModelOutput]:
    return [
        ModelOutput.from_content("mockllm", '{"items": []}'),
        ModelOutput.from_content(
            "mockllm",
            json.dumps(
                {
                    "message": message,
                    "annotations": [],
                    "alignments": [],
                    "terminology": [],
                }
            ),
        ),
    ]


def _eval_live_task(
    tmp_path: Path,
    *,
    candidate_outputs: list[ModelOutput] | None = None,
    stakeholder_outputs: list[ModelOutput] | None = None,
    max_turns: int = 2,
    max_candidate_steps_per_turn: int = 8,
    smoke: bool = False,
) -> Path:
    if smoke:
        task = phase13_smoke_interview_task(
            max_turns=max_turns,
            max_candidate_steps_per_turn=max_candidate_steps_per_turn,
        )
    else:
        task = phase13_interview_task(
            scenario_id="lab_sample_flow",
            stakeholder_profile=_profile(),
            stakeholder_seed=17,
            max_turns=max_turns,
            max_candidate_steps_per_turn=max_candidate_steps_per_turn,
            run_index=4,
        )
    logs = inspect_eval(
        task,
        model=get_model(
            "mockllm/candidate",
            custom_outputs=(
                candidate_outputs
                if candidate_outputs is not None
                else [
                    ModelOutput.from_content("mockllm", "Question?"),
                    ModelOutput.for_tool_call(
                        "mockllm", "complete_interview", {"reason": "done"}
                    ),
                ]
            ),
        ),
        model_roles={
            "stakeholder": get_model(
                "mockllm/stakeholder",
                custom_outputs=(
                    stakeholder_outputs
                    if stakeholder_outputs is not None
                    else _stakeholder_outputs()
                ),
            )
        },
        display="none",
        log_dir=str(tmp_path),
    )
    assert len(logs) == 1
    assert logs[0].location
    return Path(logs[0].location)


def test_phase14_score_extraction_ignores_unrelated_private_scorers() -> None:
    sample = SimpleNamespace(
        scores={
            "unrelated_scorer": SimpleNamespace(
                value={"truth": "private", "stakeholder_knowledge": "private"}
            ),
            "phase13_primary_scorer": SimpleNamespace(
                value={"protocol_completed": True, "truth": "private"}
            ),
        }
    )
    assert phase14._score_value(sample) == {"protocol_completed": True}


def test_phase14_usage_splits_candidate_and_stakeholder_shared_model() -> None:
    class ModelOutput:
        def __init__(self, usage: dict[str, int]) -> None:
            self.usage = usage

    class ModelEvent:
        def __init__(self, role: str | None, usage: dict[str, int]) -> None:
            self.role = role
            self.output = ModelOutput(usage)

    candidate_event = ModelEvent(
        None, {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
    )
    stakeholder_event = ModelEvent(
        "stakeholder", {"input_tokens": 20, "output_tokens": 10, "total_tokens": 30}
    )
    sample = SimpleNamespace(
        model_usage={
            "shared/model": {
                "input_tokens": 30,
                "output_tokens": 15,
                "total_tokens": 45,
            }
        },
        role_usage={
            "stakeholder": {
                "input_tokens": 20,
                "output_tokens": 10,
                "total_tokens": 30,
            }
        },
        events=[candidate_event, stakeholder_event],
    )
    usage = phase14._usage_by_role(sample, "shared/model", "shared/model")
    assert usage["candidate"]["total_tokens"] == 15
    assert usage["stakeholder"]["total_tokens"] == 30
    assert usage["total"]["total_tokens"] == 45


def test_phase14_calibration_config_has_three_reproducible_runs() -> None:
    config = load_experiment_config("experiments/phase14/calibration.json")
    assert [run.scenario_id for run in config.runs] == [
        "lab_sample_flow",
        "quotation_workflow_1",
        "quotation_workflow_1_ja",
    ]
    assert [run.run_index for run in config.runs] == [0, 1, 2]
    assert [run.stakeholder_seed for run in config.runs] == [1401, 1402, 1403]
    task_config = build_inspect_task_config(config.runs[0])
    assert task_config["scenario_id"] == "lab_sample_flow"
    assert task_config["stakeholder_seed"] == 1401
    assert "candidate_model" not in task_config
    assert "stakeholder_model" not in task_config


def test_phase14_summary_preserves_scores_usage_and_safe_provenance(tmp_path) -> None:
    log_path = _eval_live_task(tmp_path)
    summary = summarize_eval_log(log_path)
    assert summary["schema_version"] == 3
    assert len(summary["runs"]) == 1
    run = summary["runs"][0]
    assert run["run"] == {
        "candidate_model": "mockllm/candidate",
        "epoch": 1,
        "eval_id": run["run"]["eval_id"],
        "generation_parameters": {
            "candidate": {"max_tokens": 1024},
            "stakeholder": {},
        },
        "reasoning_capability_metadata": {
            "available": False,
            "reason": "not_recorded",
            "source": "Inspect eval/model metadata",
        },
        "limits": {
            "candidate_max_tokens": 1024,
            "max_candidate_steps_per_turn": 8,
            "max_interview_turns": 2,
        },
        "log_id": run["run"]["eval_id"],
        "run_id": run["run"]["run_id"],
        "run_index": 4,
        "scenario_id": "lab_sample_flow",
        "stakeholder_model": "mockllm/stakeholder",
        "requested_reasoning_effort": None,
        "stakeholder_profile_id": "phase14-test-profile",
        "stakeholder_seed": 17,
        "task": "task",
    }
    assert run["protocol"]["status"] == "completed"
    assert run["protocol"]["candidate_generation_count"] == 2
    assert run["protocol"]["stakeholder_generation_count"] == 2
    assert run["protocol"]["candidate_turns"] == 2
    assert run["protocol"]["stakeholder_turns"] == 1
    assert len(run["primary_evaluation"]) == 41
    assert run["primary_evaluation"]["protocol_completed"] is True
    assert run["diagnostics"]["failure_class"] == "completed"
    assert run["diagnostics"]["accepted_response_count"] == 1
    assert run["diagnostics"]["accepted_empty_plan_response_count"] == 1
    assert (
        run["diagnostics"]["accepted_response_with_text_but_no_annotations_count"] == 1
    )
    assert (
        run["diagnostics"]["accepted_response_with_insufficient_annotations_count"] == 0
    )
    assert run["diagnostics"]["stakeholder_plan_attempt_count"] == 1
    assert run["diagnostics"]["stakeholder_realization_attempt_count"] == 1
    assert run["diagnostics"]["stakeholder_semantic_rejection_count"] == 0
    assert run["diagnostics"]["semantic_retry_count"] == 0
    assert run["usage"]["candidate"]["total_tokens"] is not None
    assert run["usage"]["stakeholder"]["total_tokens"] is not None
    assert run["usage"]["stakeholder"]["reasoning_tokens"] is None
    assert run["usage"]["stakeholder"]["non_reasoning_output_tokens"] is None
    assert run["usage"]["stakeholder"]["reasoning_share"] is None
    assert run["usage"]["total"]["total_cost"] is None
    assert len(run["generation_usage"]["candidate"]) == 2
    assert len(run["generation_usage"]["stakeholder"]) == 2
    assert run["generation_usage"]["stakeholder"][0]["phase"] == "plan"
    assert run["generation_usage"]["stakeholder"][0]["visible_completion_chars"] > 0
    assert (
        run["generation_usage"]["stakeholder"][0]["visible_completion_estimated_tokens"]
        is None
    )

    serialized = json.dumps(summary, ensure_ascii=False, sort_keys=True)
    assert "stakeholder_knowledge" not in serialized
    assert "visible_node_ids" not in serialized
    assert "generation_seed" not in serialized
    assert "skn_" not in serialized
    assert "phase14-test-profile" in serialized


def test_phase14_missing_usage_is_reported_as_unknown(tmp_path) -> None:
    log_path = _eval_live_task(tmp_path)
    log = read_eval_log(log_path)
    assert log.samples
    stripped_sample = log.samples[0].model_copy(
        update={"model_usage": {}, "role_usage": {}, "events": [], "scores": {}}
    )
    stripped_log = log.model_copy(update={"samples": [stripped_sample]})
    summary = summarize_eval_log_object(stripped_log)
    usage = summary["runs"][0]["usage"]
    assert all(value is None for value in usage["candidate"].values())
    assert all(value is None for value in usage["stakeholder"].values())
    assert all(value is None for value in usage["total"].values())
    assert summary["runs"][0]["diagnostics"]["failure_class"] == "scoring_failure"
    assert summary["runs"][0]["diagnostics"]["accepted_response_count"] == 1
    assert summary["aggregate"]["fabricated_node_total"] is None
    assert summary["aggregate"]["fabricated_edge_total"] is None


def test_phase14_multiple_log_aggregation_is_stable(tmp_path) -> None:
    log_path = _eval_live_task(tmp_path)
    summary = summarize_eval_logs([log_path, log_path])
    assert len(summary["runs"]) == 2
    aggregate = summary["aggregate"]
    assert aggregate["run_count"] == 2
    assert aggregate["completion_rate"] == 1.0
    assert aggregate["average_candidate_generations"] == 2.0
    assert aggregate["by_scenario"]["lab_sample_flow"]["run_count"] == 2
    first = json.dumps(summary, ensure_ascii=False, sort_keys=True)
    second = json.dumps(summary, ensure_ascii=False, sort_keys=True)
    assert first == second


def test_phase14_failure_classification_and_quality_tags(tmp_path) -> None:
    log_path = _eval_live_task(
        tmp_path,
        candidate_outputs=[
            ModelOutput.for_tool_call("mockllm", "get_observations", {})
        ],
        max_turns=2,
        max_candidate_steps_per_turn=1,
        smoke=True,
    )
    run = summarize_eval_log(log_path)["runs"][0]
    assert run["diagnostics"]["failure_class"] == "candidate_step_limit"
    assert run["protocol"]["candidate_generation_count"] == 1
    assert run["protocol"]["stakeholder_turns"] == 0


def test_phase14_classifies_stakeholder_semantic_retry_exhaustion(tmp_path) -> None:
    invalid_plan = json.dumps({"items": [{"semantic_id": "missing", "mode": "value"}]})
    log_path = _eval_live_task(
        tmp_path,
        candidate_outputs=[ModelOutput.from_content("mockllm", "Question?")],
        stakeholder_outputs=[
            ModelOutput.from_content("mockllm", invalid_plan) for _ in range(3)
        ],
    )
    run = summarize_eval_log(log_path)["runs"][0]
    assert run["diagnostics"]["failure_class"] == (
        "stakeholder_semantic_validation_failure"
    )
    assert run["diagnostics"]["accepted_response_count"] == 0
    assert run["diagnostics"]["accepted_empty_plan_response_count"] == 0
    assert run["diagnostics"]["stakeholder_plan_attempt_count"] == 3
    assert run["diagnostics"]["stakeholder_realization_attempt_count"] == 0
    assert run["diagnostics"]["stakeholder_semantic_rejection_count"] == 3
    assert run["diagnostics"]["semantic_retry_count"] == 2


def test_phase14_cli_summary_has_no_model_call_or_private_dump(tmp_path) -> None:
    log_path = _eval_live_task(tmp_path)
    output_path = tmp_path / "summary.json"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "business_interview_bench.phase14",
            "summarize",
            str(log_path),
            "--output",
            str(output_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["aggregate"]["run_count"] == 1
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "stakeholder_knowledge" not in serialized
    assert "visible_node_ids" not in serialized


@pytest.mark.parametrize(
    ("candidate_outputs", "max_steps", "expected_count"),
    [
        (
            [ModelOutput.from_content("mockllm", "Question?")],
            1,
            1,
        ),
        (
            [
                ModelOutput.for_tool_call("mockllm", "get_observations", {}),
                ModelOutput.from_content("mockllm", "Question?"),
            ],
            2,
            2,
        ),
    ],
)
def test_phase14_protocol_generation_counts_are_model_invocations(
    tmp_path, candidate_outputs: list[ModelOutput], max_steps: int, expected_count: int
) -> None:
    log_path = _eval_live_task(
        tmp_path,
        candidate_outputs=candidate_outputs,
        max_turns=1,
        max_candidate_steps_per_turn=max_steps,
    )
    protocol = summarize_eval_log(log_path)["runs"][0]["protocol"]
    assert protocol["candidate_generation_count"] == expected_count


def test_phase14_completed_run_keeps_recoverable_tool_error_diagnostic(
    tmp_path,
) -> None:
    log_path = _eval_live_task(
        tmp_path,
        candidate_outputs=[
            ModelOutput.for_tool_call("mockllm", "add_node", {"node_id": "n1"}),
            ModelOutput.for_tool_call("mockllm", "add_node", {"node_id": "n1"}),
            ModelOutput.from_content("mockllm", "Question?"),
            ModelOutput.for_tool_call(
                "mockllm", "complete_interview", {"reason": "done"}
            ),
        ],
    )
    summary = summarize_eval_log(log_path)
    run = summary["runs"][0]
    assert run["diagnostics"]["failure_class"] == "completed"
    assert run["diagnostics"]["recoverable_tool_error_count"] == 1
    assert "recovered_tool_error" in run["diagnostics"]["quality_tags"]
    assert summary["aggregate"]["completion_rate"] == 1.0
    assert summary["aggregate"]["total_recoverable_tool_error_count"] == 1
    assert summary["aggregate"]["mean_recoverable_tool_error_count"] == 1.0


def test_phase14_candidate_model_crash_is_classified(tmp_path) -> None:
    log_path = _eval_live_task(tmp_path, candidate_outputs=[])
    diagnostics = summarize_eval_log(log_path)["runs"][0]["diagnostics"]
    assert diagnostics["failure_class"] == "candidate_generation_failure"
    assert diagnostics["candidate_model_error_count"] == 1
    assert diagnostics["stakeholder_model_error_count"] == 0


def test_phase14_stakeholder_model_crash_is_classified(tmp_path) -> None:
    log_path = _eval_live_task(
        tmp_path,
        stakeholder_outputs=[ModelOutput.from_content("mockllm", '{"items": []}')],
    )
    diagnostics = summarize_eval_log(log_path)["runs"][0]["diagnostics"]
    assert diagnostics["failure_class"] == "stakeholder_generation_failure"
    assert diagnostics["candidate_model_error_count"] == 0
    assert diagnostics["stakeholder_model_error_count"] == 1


def test_phase14_semantic_retry_diagnostics_exclude_rejected_what(
    tmp_path,
) -> None:
    invalid_plan = json.dumps({"items": [{"semantic_id": "missing", "mode": "value"}]})
    valid_plan = json.dumps(
        {"items": [{"semantic_id": "node:skn_001:activity", "mode": "value"}]}
    )
    valid_response = json.dumps(
        {
            "message": "I review requests.",
            "annotations": [
                {
                    "semantic_id": "node:skn_001:activity",
                    "mode": "value",
                    "quote": "review requests",
                }
            ],
            "alignments": [],
            "terminology": [],
        }
    )
    log_path = _eval_live_task(
        tmp_path,
        candidate_outputs=[
            ModelOutput.from_content("mockllm", "Question?"),
            ModelOutput.for_tool_call(
                "mockllm", "complete_interview", {"reason": "done"}
            ),
        ],
        stakeholder_outputs=[
            ModelOutput.from_content("mockllm", invalid_plan),
            ModelOutput.from_content("mockllm", valid_plan),
            ModelOutput.from_content("mockllm", valid_response),
        ],
    )
    diagnostics = summarize_eval_log(log_path)["runs"][0]["diagnostics"]
    assert diagnostics["failure_class"] == "completed"
    assert diagnostics["accepted_response_count"] == 1
    assert diagnostics["stakeholder_plan_attempt_count"] == 2
    assert diagnostics["stakeholder_realization_attempt_count"] == 1
    assert diagnostics["stakeholder_semantic_rejection_count"] == 1
    assert diagnostics["semantic_retry_count"] == 1


def test_phase14_semantic_retry_diagnostics_exclude_rejected_how(
    tmp_path,
) -> None:
    plan = json.dumps(
        {"items": [{"semantic_id": "node:skn_001:activity", "mode": "value"}]}
    )
    invalid_response = json.dumps(
        {"message": "Answer.", "annotations": [], "alignments": [], "terminology": []}
    )
    valid_response = json.dumps(
        {
            "message": "I review requests.",
            "annotations": [
                {
                    "semantic_id": "node:skn_001:activity",
                    "mode": "value",
                    "quote": "review requests",
                }
            ],
            "alignments": [],
            "terminology": [],
        }
    )
    log_path = _eval_live_task(
        tmp_path,
        candidate_outputs=[
            ModelOutput.from_content("mockllm", "Question?"),
            ModelOutput.for_tool_call(
                "mockllm", "complete_interview", {"reason": "done"}
            ),
        ],
        stakeholder_outputs=[
            ModelOutput.from_content("mockllm", plan),
            ModelOutput.from_content("mockllm", invalid_response),
            ModelOutput.from_content("mockllm", valid_response),
        ],
    )
    run = summarize_eval_log(log_path)["runs"][0]
    diagnostics = run["diagnostics"]
    assert diagnostics["failure_class"] == "completed"
    assert diagnostics["accepted_response_with_text_but_no_annotations_count"] == 0
    assert diagnostics["accepted_response_with_insufficient_annotations_count"] == 0
    assert diagnostics["stakeholder_plan_attempt_count"] == 1
    assert diagnostics["stakeholder_realization_attempt_count"] == 2
    assert diagnostics["stakeholder_semantic_rejection_count"] == 1
    assert diagnostics["semantic_retry_count"] == 1


def test_phase14_run_config_is_formal_and_resolves_models(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PHASE14_CANDIDATE_MODEL", "mockllm/candidate")
    monkeypatch.setenv("PHASE14_STAKEHOLDER_MODEL", "mockllm/stakeholder")
    config = load_experiment_config("experiments/phase14/calibration.json")
    run_config = build_inspect_run_config(config.runs[0])

    parsed = RunConfigInput.model_validate(run_config)
    assert parsed.task is not None
    model_entry = parsed.model
    assert model_entry is not None
    assert not isinstance(model_entry, str)
    assert model_entry.model == "mockllm/candidate"
    assert parsed.model_roles["stakeholder"].model == "mockllm/stakeholder"
    assert parsed.generate_config.temperature == 0.0
    assert parsed.eval_config.epochs == 1
    assert run_config["task"]["args"]["candidate_max_tokens"] == 1024
    assert "stakeholder_knowledge" not in json.dumps(run_config)
    assert "${PHASE14_" not in json.dumps(run_config)

    config_path = tmp_path / "run-config.json"
    config_path.write_text(json.dumps(run_config), encoding="utf-8")
    params = parse_run_config(str(config_path))
    candidate = get_model(
        "mockllm/candidate",
        custom_outputs=[
            ModelOutput.from_content("mockllm", "Question?"),
            ModelOutput.for_tool_call(
                "mockllm", "complete_interview", {"reason": "done"}
            ),
        ],
    )
    stakeholder = get_model(
        "mockllm/stakeholder",
        custom_outputs=[
            ModelOutput.from_content("mockllm", '{"items": []}'),
            ModelOutput.from_content(
                "mockllm",
                '{"message":"Answer.","annotations":[],"alignments":[],"terminology":[]}',
            ),
        ],
    )
    logs = inspect_eval(
        params["tasks"],
        model=candidate,
        task_args=params["task_args"],
        model_roles={"stakeholder": stakeholder},
        temperature=params["temperature"],
        epochs=params["epochs"],
        display="none",
        log_dir=str(tmp_path),
    )
    assert len(logs) == 1
    assert logs[0].status == "success"
    assert logs[0].samples
    scores = logs[0].samples[0].scores
    assert scores is not None
    score_value = cast(dict[str, Any], scores["phase13_primary_scorer"].value)
    assert score_value["protocol_completed"] is True


def test_phase14_run_config_rejects_token_bound_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PHASE14_CANDIDATE_MODEL", "mockllm/candidate")
    monkeypatch.setenv("PHASE14_STAKEHOLDER_MODEL", "mockllm/stakeholder")
    config = load_experiment_config("experiments/phase14/calibration.json")
    run = config.runs[0].model_copy(
        update={"candidate_generation": {"max_tokens": 512}}
    )
    with pytest.raises(ValueError, match="candidate_generation.max_tokens"):
        build_inspect_run_config(run)


def test_phase14_missing_model_placeholder_is_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PHASE14_CANDIDATE_MODEL", raising=False)
    monkeypatch.setenv("PHASE14_STAKEHOLDER_MODEL", "mockllm/stakeholder")
    config = load_experiment_config("experiments/phase14/calibration.json")
    with pytest.raises(ValueError, match="PHASE14_CANDIDATE_MODEL"):
        build_inspect_run_config(config.runs[0])
