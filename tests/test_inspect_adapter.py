"""Public Inspect adapter tests for deterministic seed 9004 replay."""

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
from business_interview_bench.inspect_adapter import (
    BusinessInterviewReplayStore,
    load_seed9004_store_payload,
    primary_evaluation_field_names,
    replay_inputs_from_store,
    seed9004_replay_dataset,
    seed9004_replay_metadata,
    seed9004_replay_solver,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TASK_NAME = "business_interview_bench/seed9004_replay"
SCORER_NAME = "business_interview_bench/primary_scorer"


def _cli_environment() -> dict[str, str]:
    env = os.environ.copy()
    # Prove that an ambient model selection cannot cause a call when the CLI
    # explicitly receives ``--model none``.
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


def test_inspect_entrypoint_loads_registry_module() -> None:
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


def test_seed9004_dataset_has_exactly_one_sample() -> None:
    dataset = seed9004_replay_dataset()

    assert len(dataset) == 1
    sample = dataset[0]
    assert sample.id == "seed9004"
    assert sample.metadata is not None
    assert sample.metadata["scenario_id"] == "quotation_workflow_1"
    assert sample.metadata["source_commit_sha"] == (
        "00a98a5efbe9db2ccc3aaf2f04529ef50c323bb0"
    )


def test_task_registry_resolves_through_cli(live_replay: tuple[Path, EvalLog]) -> None:
    _, log = live_replay

    assert log.eval.task == TASK_NAME


def test_scorer_registry_resolves_through_cli(
    offline_replay: tuple[Path, EvalLog],
) -> None:
    _, log = offline_replay

    score = _primary_score(log)
    assert score.metadata is not None
    assert score.metadata["headline_field"] == "reconstruction_pass"


def test_replay_solver_does_not_call_generate() -> None:
    async def forbidden_generate(_state: TaskState, **_kwargs: Any) -> TaskState:
        raise AssertionError("replay solver called generate")

    state = TaskState(
        model=cast(ModelName, "none"),
        sample_id="seed9004",
        epoch=1,
        input="replay",
        messages=[],
        metadata=seed9004_replay_metadata(),
    )
    solved = asyncio.run(
        seed9004_replay_solver()(state, cast(Generate, forbidden_generate))
    )

    assert solved.completed
    assert solved.store_as(BusinessInterviewReplayStore).replay_case_id == "seed9004"


def test_live_log_contains_no_model_calls(
    live_replay: tuple[Path, EvalLog],
) -> None:
    _, log = live_replay
    sample = _sample(log)

    assert sample.model_usage == {}
    assert all(type(event).__name__ != "ModelEvent" for event in sample.events)


def test_live_log_store_contains_exact_agent_payload(
    live_replay: tuple[Path, EvalLog],
) -> None:
    stored = _store_model(live_replay[1])
    expected = AgentGraph.model_validate(
        load_seed9004_payload("agent.json")
    ).model_dump(mode="json")

    assert stored.agent == expected


def test_live_log_store_contains_exact_truth_payload(
    live_replay: tuple[Path, EvalLog],
) -> None:
    stored = _store_model(live_replay[1])
    expected = BusinessProcessGraph.model_validate(
        load_seed9004_payload("truth.json")
    ).model_dump(mode="json")

    assert stored.truth == expected


def test_live_log_store_contains_exact_context_payload(
    live_replay: tuple[Path, EvalLog],
) -> None:
    stored = _store_model(live_replay[1])
    expected = InterviewEvaluationContext.model_validate(
        load_seed9004_payload("evaluation_context.json")
    ).model_dump(mode="json")

    assert stored.evaluation_context == expected


def test_live_log_store_contains_exact_knowledge_coverage_payload(
    live_replay: tuple[Path, EvalLog],
) -> None:
    stored = _store_model(live_replay[1])
    expected = KnowledgeCoverageView.model_validate(
        load_seed9004_payload("knowledge_coverage.json")
    ).model_dump(mode="json")

    assert stored.knowledge_coverage == expected


def test_live_log_store_contains_provenance_and_expected_payloads(
    live_replay: tuple[Path, EvalLog],
) -> None:
    stored = _store_model(live_replay[1])

    assert stored.provenance == load_seed9004_payload("provenance.json")
    assert stored.expected == load_seed9004_payload("expected.json")
    assert stored.stakeholder_knowledge is None


def test_store_round_trips_to_all_core_models(
    live_replay: tuple[Path, EvalLog],
) -> None:
    stored = _store_model(live_replay[1])
    restored = replay_inputs_from_store(stored)
    agent, truth, context, knowledge_coverage = restored

    assert agent == AgentGraph.model_validate(stored.agent)
    assert truth == BusinessProcessGraph.model_validate(stored.truth)
    assert context == InterviewEvaluationContext.model_validate(
        stored.evaluation_context
    )
    assert knowledge_coverage == KnowledgeCoverageView.model_validate(
        stored.knowledge_coverage
    )


def test_store_from_logged_events_reconstructs_same_store(
    live_replay: tuple[Path, EvalLog],
) -> None:
    sample = _sample(read_eval_log(live_replay[0], resolve_attachments="core"))
    from_events = store_from_events_as(sample.events, BusinessInterviewReplayStore)
    from_sample = _store_model(live_replay[1])

    assert from_events.agent == from_sample.agent
    assert from_events.truth == from_sample.truth
    assert from_events.evaluation_context == from_sample.evaluation_context
    assert from_events.knowledge_coverage == from_sample.knowledge_coverage
    replay_inputs_from_store(from_events)


def test_logged_store_has_all_replay_fields(
    live_replay: tuple[Path, EvalLog],
) -> None:
    sample = _sample(live_replay[1])
    field_names = set(BusinessInterviewReplayStore.model_fields) - {
        "store",
        "instance",
    }

    assert {
        key.removeprefix("BusinessInterviewReplayStore:") for key in sample.store
    } >= field_names


def test_scorer_returns_exactly_41_named_values(
    live_replay: tuple[Path, EvalLog],
) -> None:
    score = _primary_score(live_replay[1])
    values = score.value
    field_names = primary_evaluation_field_names()

    assert len(field_names) == 41
    assert isinstance(values, dict)
    assert len(values) == 41
    assert set(values) == set(field_names)
    assert set(field_names) == {field.name for field in fields(PrimaryEvaluation)}
    assert score.metadata["field_count"] == 41
    assert score.metadata["aggregate_total"] is False


def test_live_replay_matches_seed9004_oracle_41_of_41(
    live_replay: tuple[Path, EvalLog],
) -> None:
    actual = _primary_score(live_replay[1]).value
    expected = load_seed9004_payload("expected.json")["oracle"]["fields"]

    assert actual == expected


def test_offline_rescore_matches_seed9004_oracle_41_of_41(
    offline_replay: tuple[Path, EvalLog],
) -> None:
    actual = _primary_score(offline_replay[1]).value
    expected = load_seed9004_payload("expected.json")["oracle"]["fields"]

    assert actual == expected


def test_live_score_equals_offline_rescore_exactly(
    live_replay: tuple[Path, EvalLog],
    offline_replay: tuple[Path, EvalLog],
) -> None:
    live_score = _primary_score(live_replay[1])
    offline_score = _primary_score(offline_replay[1])

    assert live_score.model_dump(mode="json") == offline_score.model_dump(mode="json")


def test_package_replay_runs_without_source_checkout(
    tmp_path: Path,
) -> None:
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


def test_runtime_replay_asset_has_no_test_fixture_copy() -> None:
    asset_root = PROJECT_ROOT / "src" / "business_interview" / "replay_data"

    legacy_alias = PROJECT_ROOT / "tests" / "fixtures" / "seed9004"
    assert legacy_alias.is_symlink()
    assert legacy_alias.resolve() == asset_root / "seed9004"
    assert set(path.name for path in (asset_root / "seed9004").iterdir()) == set(
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


def test_model_none_path_requires_no_api_credentials(
    live_replay: tuple[Path, EvalLog],
) -> None:
    _, log = live_replay

    assert log.eval.model == "none/none"
    assert _sample(log).model_usage == {}


def test_store_payload_helper_matches_solver_payload(
    live_replay: tuple[Path, EvalLog],
) -> None:
    stored = _store_model(live_replay[1])
    payload = load_seed9004_store_payload()

    assert stored.agent == payload["agent"]
    assert stored.truth == payload["truth"]
    assert stored.evaluation_context == payload["evaluation_context"]
    assert stored.knowledge_coverage == payload["knowledge_coverage"]
