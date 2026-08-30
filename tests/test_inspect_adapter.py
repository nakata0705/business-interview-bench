"""Acceptance tests for the minimal Inspect seed 9004 replay adapter."""

# The workspace-level auxiliary resolver may not see the Inspect dev group.
# Project-level ``uv run pyright`` remains the authoritative adapter check.
# pyright: reportMissingImports=false

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
from dataclasses import fields
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any, cast

import pytest
from inspect_ai.log import EvalLog, read_eval_log
from inspect_ai.model import ModelName
from inspect_ai.solver import Generate, TaskState
from inspect_ai.util import store_from_events_as

from business_interview.evaluation import KnowledgeCoverageView, PrimaryEvaluation
from business_interview.models import (
    AgentGraph,
    BusinessProcessGraph,
    InterviewEvaluationContext,
)
from business_interview.replay_data import (
    SEED9004_FILES,
    load_seed9004_payload,
)
from business_interview_bench.inspect_adapter import BusinessInterviewReplayStore
from business_interview_bench.inspect_adapter.dataset import seed9004_replay_dataset
from business_interview_bench.inspect_adapter.solver import seed9004_replay_solver

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TASK_NAME = "business_interview_bench/seed9004_replay"
SCORER_NAME = "business_interview_bench/primary_scorer"
STORE_FIELDS = {
    "agent",
    "truth",
    "evaluation_context",
    "knowledge_coverage",
}


def _cli_environment() -> dict[str, str]:
    env = os.environ.copy()
    # An explicit ``--model none`` must win over ambient model configuration.
    env["INSPECT_EVAL_MODEL"] = "openai/gpt-4o"
    for name in (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GOOGLE_API_KEY",
        "GEMINI_API_KEY",
        "MISTRAL_API_KEY",
        "COHERE_API_KEY",
    ):
        env.pop(name, None)
    return env


def _inspect_binary() -> str:
    binary = shutil.which("inspect")
    assert binary is not None, "inspect-ai CLI is not installed"
    return binary


def _sample(log: EvalLog) -> Any:
    assert log.samples is not None
    assert len(log.samples) == 1
    return log.samples[0]


def _primary_score(log: EvalLog) -> Any:
    sample = _sample(log)
    assert sample.scores is not None
    assert "primary_scorer" in sample.scores
    return sample.scores["primary_scorer"]


def _store_model(log: EvalLog) -> BusinessInterviewReplayStore:
    sample = _sample(log)
    state = TaskState(
        model=cast(ModelName, "none"),
        sample_id=sample.id,
        epoch=sample.epoch,
        input=sample.input,
        messages=sample.messages,
        target=sample.target,
        store=sample.store,
    )
    return state.store_as(BusinessInterviewReplayStore)


def _oracle_fields() -> dict[str, Any]:
    expected = load_seed9004_payload("expected.json")
    return expected["oracle"]["fields"]


@pytest.fixture(scope="module")
def live_replay(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, EvalLog]:
    log_dir = tmp_path_factory.mktemp("inspect-live")
    result = subprocess.run(
        [
            _inspect_binary(),
            "eval",
            TASK_NAME,
            "--model",
            "none",
            "--display",
            "none",
            "--log-format",
            "eval",
            "--log-dir",
            str(log_dir),
        ],
        cwd=PROJECT_ROOT,
        env=_cli_environment(),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    log_paths = sorted(log_dir.glob("*.eval"))
    assert len(log_paths) == 1
    log = read_eval_log(log_paths[0])
    assert log.status == "success"
    assert len(log.samples or []) == 1
    return log_paths[0], log


@pytest.fixture(scope="module")
def offline_replay(
    live_replay: tuple[Path, EvalLog],
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[Path, EvalLog]:
    live_path, _ = live_replay
    output_path = tmp_path_factory.mktemp("inspect-offline") / "rescored.eval"
    result = subprocess.run(
        [
            _inspect_binary(),
            "score",
            str(live_path),
            "--model",
            "none",
            "--scorer",
            SCORER_NAME,
            "--display",
            "none",
            "--action",
            "overwrite",
            "--output-file",
            str(output_path),
        ],
        cwd=PROJECT_ROOT,
        env=_cli_environment(),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert output_path.is_file()
    log = read_eval_log(output_path)
    assert log.status == "success"
    assert len(log.samples or []) == 1
    return output_path, log


def test_registry_and_dataset_are_minimal() -> None:
    matches = [
        entry_point
        for entry_point in entry_points(group="inspect_ai")
        if entry_point.name == "business_interview_bench"
    ]
    assert len(matches) == 1
    module = matches[0].load()
    assert module.__name__ == "business_interview_bench.inspect_adapter._registry"
    assert hasattr(module, "seed9004_replay")
    assert hasattr(module, "primary_scorer")
    assert not hasattr(module, "reconstruction_pass_metric")

    dataset = seed9004_replay_dataset()
    assert len(dataset) == 1
    sample = dataset[0]
    assert sample.id == "seed9004"
    assert sample.input == "seed9004 replay"
    assert sample.metadata == {
        "replay_case_id": "seed9004",
        "scenario_id": "quotation_workflow_1",
        "source_commit_sha": "00a98a5efbe9db2ccc3aaf2f04529ef50c323bb0",
    }


def test_store_schema_and_solver_only_persist_scoring_inputs() -> None:
    assert set(BusinessInterviewReplayStore.model_fields) - {"store", "instance"} == (
        STORE_FIELDS
    )

    async def forbidden_generate(_state: TaskState, **_kwargs: Any) -> TaskState:
        raise AssertionError("replay solver called generate")

    state = TaskState(
        model=cast(ModelName, "none"),
        sample_id="seed9004",
        epoch=1,
        input="replay",
        messages=[],
    )
    solved = asyncio.run(
        seed9004_replay_solver()(state, cast(Generate, forbidden_generate))
    )

    assert solved.completed
    stored = solved.store_as(BusinessInterviewReplayStore)
    assert set(stored.model_dump()) == STORE_FIELDS


def test_live_replay_has_exact_inputs_oracle_and_no_model_calls(
    live_replay: tuple[Path, EvalLog],
) -> None:
    _, log = live_replay
    sample = _sample(log)
    stored = _store_model(log)

    assert log.eval.task == TASK_NAME
    assert log.eval.model == "none/none"
    assert sample.model_usage == {}
    assert all(type(event).__name__ != "ModelEvent" for event in sample.events)
    assert {
        key.removeprefix("BusinessInterviewReplayStore:")
        for key in sample.store
        if not key.endswith(":instance")
    } == STORE_FIELDS

    assert stored.agent == AgentGraph.model_validate(
        load_seed9004_payload("agent.json")
    ).model_dump(mode="json")
    assert stored.truth == BusinessProcessGraph.model_validate(
        load_seed9004_payload("truth.json")
    ).model_dump(mode="json")
    assert stored.evaluation_context == InterviewEvaluationContext.model_validate(
        load_seed9004_payload("evaluation_context.json")
    ).model_dump(mode="json")
    assert stored.knowledge_coverage == KnowledgeCoverageView.model_validate(
        load_seed9004_payload("knowledge_coverage.json")
    ).model_dump(mode="json")

    score = _primary_score(log)
    assert score.value == _oracle_fields()
    assert len(score.value) == 41
    assert set(score.value) == {field.name for field in fields(PrimaryEvaluation)}
    assert log.results is not None
    assert log.results.scores
    assert log.results.scores[0].name == "reconstruction_pass"
    assert set(log.results.scores[0].metrics) == {"mean"}


def test_offline_rescore_matches_oracle_and_live_exactly(
    live_replay: tuple[Path, EvalLog],
    offline_replay: tuple[Path, EvalLog],
) -> None:
    live_score = _primary_score(live_replay[1])
    offline_log = offline_replay[1]
    offline_score = _primary_score(offline_log)

    assert _sample(offline_log).model_usage == {}
    assert offline_score.value == _oracle_fields()
    assert len(offline_score.value) == 41
    assert live_score.model_dump(mode="json") == offline_score.model_dump(mode="json")


def test_store_payload_round_trips_to_core_models(
    live_replay: tuple[Path, EvalLog],
) -> None:
    stored = _store_model(live_replay[1])
    agent = AgentGraph.model_validate(stored.agent)
    truth = BusinessProcessGraph.model_validate(stored.truth)
    context = InterviewEvaluationContext.model_validate(stored.evaluation_context)
    knowledge_coverage = KnowledgeCoverageView.model_validate(stored.knowledge_coverage)

    assert agent.model_dump(mode="json") == stored.agent
    assert truth.model_dump(mode="json") == stored.truth
    assert context.model_dump(mode="json") == stored.evaluation_context
    assert knowledge_coverage.model_dump(mode="json") == stored.knowledge_coverage


def test_logged_store_round_trips_from_inspect_events(
    live_replay: tuple[Path, EvalLog],
) -> None:
    sample = _sample(read_eval_log(live_replay[0], resolve_attachments="core"))
    from_events = store_from_events_as(sample.events, BusinessInterviewReplayStore)
    from_sample = _store_model(live_replay[1])

    assert from_events.model_dump() == from_sample.model_dump()
    AgentGraph.model_validate(from_events.agent)
    BusinessProcessGraph.model_validate(from_events.truth)
    InterviewEvaluationContext.model_validate(from_events.evaluation_context)
    KnowledgeCoverageView.model_validate(from_events.knowledge_coverage)


def test_replay_runs_without_source_checkout(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    result = subprocess.run(
        [
            _inspect_binary(),
            "eval",
            TASK_NAME,
            "--model",
            "none",
            "--display",
            "none",
            "--log-format",
            "eval",
            "--log-dir",
            str(log_dir),
        ],
        cwd=tmp_path,
        env=_cli_environment() | {"PYTHONPATH": ""},
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    paths = list(log_dir.glob("*.eval"))
    assert len(paths) == 1
    assert read_eval_log(paths[0]).status == "success"


def test_runtime_asset_has_one_packaged_source_of_truth() -> None:
    asset_root = PROJECT_ROOT / "src" / "business_interview" / "replay_data"
    assert not (PROJECT_ROOT / "tests" / "fixtures" / "seed9004").exists()
    assert {path.name for path in (asset_root / "seed9004").iterdir()} == set(
        SEED9004_FILES
    )


def test_core_imports_do_not_import_inspect_ai(tmp_path: Path) -> None:
    code = """
import sys
import business_interview.evaluation
import business_interview.models
import business_interview.replay_data
import business_interview.scenarios
import business_interview.stakeholders
assert "inspect_ai" not in sys.modules
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = ""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
