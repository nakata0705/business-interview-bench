"""Phase 21 Candidate outcome and safe-diagnostics coverage."""

# The workspace-level auxiliary resolver may not see Inspect's dev group or
# freshly added adapter siblings; project-level ``uv run pyright`` is
# authoritative for this package.
# pyright: reportMissingImports=false

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Callable

import pytest
from inspect_ai import eval as inspect_eval
from inspect_ai.log import read_eval_log
from inspect_ai.model import ChatCompletionChoice, ModelOutput, get_model

import business_interview_bench.phase14 as phase14
from business_interview_bench.inspect_adapter.candidate import (
    classify_candidate_output,
)
from business_interview_bench.inspect_adapter.multiturn import (
    phase13_smoke_interview_task,
)


class ModelEvent:
    def __init__(self, role: str | None, output: object) -> None:
        self.role = role
        self.output = output
        self.config = {"max_tokens": 1024}


class ToolEvent:
    def __init__(self, function: str, error: str | None = None) -> None:
        self.function = function
        self.error = error


def test_candidate_classifier_separates_question_tool_blank_limit_and_provider() -> (
    None
):
    question = classify_candidate_output(
        ModelOutput.from_content("mockllm", "Question?")
    )
    tool = classify_candidate_output(
        ModelOutput.for_tool_call("mockllm", "get_agent_graph", {})
    )
    blank = classify_candidate_output(ModelOutput.from_content("mockllm", ""))
    exhausted = classify_candidate_output(
        ModelOutput.from_content("mockllm", "partial", stop_reason="max_tokens")
    )
    provider = classify_candidate_output(
        ModelOutput.from_content("mockllm", "", error="provider unavailable")
    )
    invalid = classify_candidate_output(
        SimpleNamespace(
            stop_reason="tool_calls",
            completion="",
            message=SimpleNamespace(
                tool_calls=[SimpleNamespace(function=None, parse_error="invalid")]
            ),
        )
    )
    unknown = classify_candidate_output(
        SimpleNamespace(stop_reason="unknown", completion="")
    )
    absent_stop = classify_candidate_output(SimpleNamespace(completion=""))
    absent_text = classify_candidate_output(
        SimpleNamespace(completion="Question without a stop reason")
    )
    unknown_with_tool = classify_candidate_output(
        SimpleNamespace(
            stop_reason="unknown",
            completion="",
            message=SimpleNamespace(
                tool_calls=[SimpleNamespace(function="add_node", parse_error=None)]
            ),
        )
    )

    assert question.outcome_kind == "question"
    assert question.produced_question
    assert tool.outcome_kind == "tool_call"
    assert tool.tool_names == ("get_agent_graph",)
    assert blank.outcome_kind == "empty_completion"
    assert exhausted.outcome_kind == "output_exhaustion"
    assert exhausted.hit_output_limit
    assert not exhausted.produced_question
    assert provider.outcome_kind == "provider_error"
    assert invalid.outcome_kind == "invalid_tool_call"
    assert unknown.outcome_kind == "provider_error"
    assert absent_stop.outcome_kind == "provider_error"
    assert absent_text.outcome_kind == "provider_error"
    assert unknown_with_tool.outcome_kind == "provider_error"


def test_candidate_generation_records_are_turn_and_step_addressable() -> None:
    sample = SimpleNamespace(
        events=[
            ModelEvent(
                None,
                ModelOutput.for_tool_call("mockllm", "add_node", {}),
            ),
            ToolEvent("add_node", error="recoverable duplicate"),
            ModelEvent(None, ModelOutput.from_content("mockllm", "Question?")),
            ModelEvent("stakeholder", ModelOutput.from_content("mockllm", "Answer.")),
            ModelEvent(
                None,
                ModelOutput.from_content(
                    "mockllm", "truncated", stop_reason="model_length"
                ),
            ),
        ],
        metadata={},
        store={
            "BusinessInterviewLiveStore:live_state": {
                "protocol_state": {"failure_reason": "candidate_output_exhausted"}
            }
        },
    )
    records = phase14._candidate_generation_records(
        sample,
        configured_max_tokens=1024,
        requested_reasoning_effort="low",
        warnings=[],
    )
    diagnostics = phase14._candidate_diagnostics(sample, records, {})

    assert [
        (item["interview_turn_index"], item["candidate_step_index"]) for item in records
    ] == [
        (1, 1),
        (1, 2),
        (2, 1),
    ]
    assert [item["outcome_kind"] for item in records] == [
        "tool_call",
        "question",
        "output_exhaustion",
    ]
    assert records[0]["configured_max_tokens"] == 1024
    assert records[0]["requested_reasoning_effort"] == "low"
    assert records[0]["tool_error_count"] == 1
    assert diagnostics["candidate_output_exhaustion_count"] == 1
    assert diagnostics["candidate_generations_at_max_tokens_count"] == 1
    assert diagnostics["candidate_question_generation_count"] == 1
    assert diagnostics["candidate_tool_generation_count"] == 1
    assert diagnostics["candidate_tool_call_counts"] == {"add_node": 1}
    assert diagnostics["candidate_tool_error_counts"] == {"add_node": 1}
    assert diagnostics["candidate_tool_call_category_counts"] == {"graph_mutations": 1}
    assert diagnostics["candidate_tool_error_category_counts"] == {"graph_mutations": 1}
    assert diagnostics["candidate_terminal_reason"] == "candidate_output_exhausted"
    assert diagnostics["candidate_true_no_question_count"] == 0
    assert diagnostics["candidate_tool_call_sequences"] == [
        {
            "interview_turn_index": 1,
            "steps": [
                {
                    "candidate_step_index": 1,
                    "tool_call_count": 1,
                    "tool_names": ["add_node"],
                    "tool_error_count": 1,
                }
            ],
        }
    ]


def test_candidate_blank_completion_is_true_no_question_not_exhaustion() -> None:
    sample = SimpleNamespace(
        events=[ModelEvent(None, ModelOutput.from_content("mockllm", ""))],
        metadata={},
        store={
            "BusinessInterviewLiveStore:live_state": {
                "protocol_state": {"failure_reason": "candidate_did_not_ask_question"}
            }
        },
    )
    records = phase14._candidate_generation_records(
        sample,
        configured_max_tokens=1024,
        requested_reasoning_effort=None,
        warnings=[],
    )
    diagnostics = phase14._candidate_diagnostics(sample, records, {})

    assert diagnostics["candidate_empty_completion_count"] == 1
    assert diagnostics["candidate_output_exhaustion_count"] == 0
    assert diagnostics["candidate_generations_at_max_tokens_count"] == 0
    assert diagnostics["candidate_true_no_question_count"] == 1
    assert diagnostics["candidate_did_not_ask_question_count"] == 1


def _mixed_exhausted_tool_output() -> ModelOutput:
    tool_output = ModelOutput.for_tool_call(
        "mockllm", "complete_interview", {"reason": "truncated"}
    )
    return ModelOutput(
        model="mockllm",
        choices=[
            ChatCompletionChoice(
                message=tool_output.message,
                stop_reason="max_tokens",
            )
        ],
        completion=tool_output.completion,
    )


def _run_smoke_candidate(
    tmp_path: Path,
    output_factory: Callable[[], ModelOutput],
) -> dict:
    task = phase13_smoke_interview_task(
        max_turns=1,
        max_candidate_steps_per_turn=2,
    )
    logs = inspect_eval(
        task,
        model=get_model(
            "mockllm/candidate",
            custom_outputs=[output_factory()],
        ),
        display="none",
        log_dir=str(tmp_path),
    )
    assert len(logs) == 1
    summary = phase14.summarize_eval_log_object(read_eval_log(logs[0].location))
    return summary["runs"][0]


def test_runtime_does_not_execute_tools_from_exhausted_output(tmp_path: Path) -> None:
    run = _run_smoke_candidate(tmp_path, _mixed_exhausted_tool_output)

    assert run["protocol"]["failure_reason"] == "candidate_output_exhausted"
    assert run["protocol"]["completion_reason"] is None
    assert run["protocol"]["candidate_generation_count"] == 1
    assert run["diagnostics"]["candidate_tool_generation_count"] == 1
    assert run["diagnostics"]["candidate_total_tool_call_count"] == 1
    assert run["diagnostics"]["candidate_tool_call_counts"] == {"complete_interview": 1}


@pytest.mark.parametrize(
    ("output_factory", "failure_reason", "failure_class"),
    [
        (
            lambda: ModelOutput.from_content(
                "mockllm", "truncated", stop_reason="max_tokens"
            ),
            "candidate_output_exhausted",
            "candidate_output_exhausted",
        ),
        (
            lambda: ModelOutput.from_content("mockllm", ""),
            "candidate_did_not_ask_question",
            "candidate_did_not_ask_question",
        ),
        (
            lambda: ModelOutput.from_content(
                "mockllm", "", error="provider unavailable"
            ),
            "candidate_generation_failure",
            "candidate_generation_failure",
        ),
        (
            lambda: ModelOutput.from_content("mockllm", "", stop_reason="unknown"),
            "candidate_generation_failure",
            "candidate_generation_failure",
        ),
    ],
)
def test_runtime_persists_distinct_candidate_terminal_outcomes(
    tmp_path: Path,
    output_factory: Callable[[], ModelOutput],
    failure_reason: str,
    failure_class: str,
) -> None:
    run = _run_smoke_candidate(tmp_path, output_factory)
    assert run["protocol"]["failure_reason"] == failure_reason
    assert run["diagnostics"]["failure_class"] == failure_class
    if failure_reason == "candidate_output_exhausted":
        assert run["diagnostics"]["candidate_output_exhaustion_count"] == 1
        assert run["diagnostics"]["candidate_generations_at_max_tokens_count"] == 1
    elif failure_reason == "candidate_did_not_ask_question":
        assert run["diagnostics"]["candidate_empty_completion_count"] == 1
        assert run["diagnostics"]["candidate_output_exhaustion_count"] == 0
    else:
        assert run["diagnostics"]["candidate_provider_error_count"] == 1
