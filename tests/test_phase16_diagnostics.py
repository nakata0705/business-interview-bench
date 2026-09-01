"""Deterministic Phase 16 usage and attempt diagnostics tests."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from types import SimpleNamespace
from typing import Any, cast

import business_interview_bench.phase14 as phase14


class ModelEvent:
    def __init__(
        self,
        *,
        role: str | None,
        completion: str,
        usage: Mapping[str, int | float] | None,
        input_text: str = "",
    ) -> None:
        self.role = role
        self.model = "shared/model"
        self.input = [SimpleNamespace(text=input_text)]
        self.output = SimpleNamespace(completion=completion, usage=usage)


class ToolEvent:
    def __init__(self, error: str) -> None:
        self.error = error


def _usage(
    input_tokens: int,
    output_tokens: int,
    reasoning_tokens: int | None,
    total_tokens: int,
) -> dict[str, int]:
    value = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }
    if reasoning_tokens is not None:
        value["reasoning_tokens"] = reasoning_tokens
    return value


def _runtime(
    *, accepted: bool = True, failure_reason: str | None = None
) -> dict[str, Any]:
    observation = {
        "id": "obs_private",
        "turn": 1,
        "text": "PRIVATE-STAKEHOLDER-KNOWLEDGE",
    }
    entries: list[dict[str, Any]] = []
    if accepted:
        entries.append(
            {
                "observation_id": observation["id"],
                "public_message_turn": 1,
                "plan": {"items": []},
                "annotations": [],
            }
        )
    return {
        "scenario_id": "lab_sample_flow",
        "protocol_state": {
            "status": "incomplete" if failure_reason else "completed",
            "failure_reason": failure_reason,
        },
        "observations": [observation],
        "initial_observation_count": 0,
        "semantic_ledger": {"entries": entries},
        "candidate_turns": 1,
        "candidate_steps": 1,
        "stakeholder_turns": 1,
        "question_count": 1,
        "max_interview_turns": 2,
        "max_candidate_steps_per_turn": 8,
        "candidate_max_tokens": 1024,
    }


def _sample(
    events: Sequence[object],
    *,
    accepted: bool = True,
    failure_reason: str | None = None,
) -> SimpleNamespace:
    stakeholder_usage = {
        "input_tokens": 40,
        "output_tokens": 100,
        "reasoning_tokens": 76,
        "total_tokens": 110,
    }
    total_usage = {
        "input_tokens": 45,
        "output_tokens": 105,
        "reasoning_tokens": 78,
        "total_tokens": 115,
    }
    return SimpleNamespace(
        events=events,
        store={
            "BusinessInterviewLiveStore:live_state": _runtime(
                accepted=accepted, failure_reason=failure_reason
            ),
            "BusinessInterviewLiveStore:stakeholder_profile": {
                "stakeholder_id": "phase16-safe-profile",
                "stakeholder_knowledge": "PRIVATE-KNOWLEDGE-MUST-NOT-LEAK",
            },
            "BusinessInterviewLiveStore:stakeholder_seed": 1401,
        },
        metadata={},
        epoch=1,
        scores={},
        model_usage={"shared/model": total_usage},
        role_usage={"stakeholder": stakeholder_usage},
    )


def _log(sample: SimpleNamespace, *, status: str = "success") -> SimpleNamespace:
    return SimpleNamespace(
        eval=SimpleNamespace(
            model="shared/model",
            model_roles={"stakeholder": "shared/model"},
            eval_id="eval-phase16",
            run_id="run-phase16",
            task_registry_name="business_interview_bench/phase13_interview",
            task_args_passed={"candidate_max_tokens": 1024},
            model_generate_config={"max_tokens": 1024},
        ),
        plan=None,
        samples=[sample],
        status=status,
    )


def _diagnostic_sample() -> SimpleNamespace:
    return _sample(
        [
            ModelEvent(
                role=None,
                completion="PRIVATE-CANDIDATE-COMPLETION",
                usage=_usage(5, 5, 2, 5),
            ),
            ModelEvent(
                role="stakeholder",
                completion="PRIVATE-PLAN-FIRST",
                usage=_usage(10, 10, 6, 11),
                input_text=phase14._PLAN_PROMPT_MARKER,
            ),
            ModelEvent(
                role="stakeholder",
                completion="PRIVATE-PLAN-ACCEPTED",
                usage=_usage(10, 20, 10, 22),
                input_text=(
                    f"{phase14._PLAN_PROMPT_MARKER} {phase14._RETRY_PROMPT_MARKER}"
                ),
            ),
            ModelEvent(
                role="stakeholder",
                completion="PRIVATE-REALIZATION-FIRST",
                usage=_usage(10, 30, 25, 33),
                input_text=phase14._REALIZATION_PROMPT_MARKER,
            ),
            ModelEvent(
                role="stakeholder",
                completion="PRIVATE-REALIZATION-ACCEPTED",
                usage=_usage(10, 40, 35, 44),
                input_text=(
                    f"{phase14._REALIZATION_PROMPT_MARKER} "
                    f"{phase14._RETRY_PROMPT_MARKER}"
                ),
            ),
        ]
    )


def test_usage_reasoning_accounting_is_safe_for_missing_and_contradictory_fields() -> (
    None
):
    warnings: list[str] = []
    measured = phase14._usage(
        {
            "input_tokens": 3,
            "output_tokens": 12,
            "reasoning_tokens": 5,
            "total_tokens": 15,
            "total_cost": 0.25,
        },
        warnings=warnings,
    )
    assert measured["reasoning_tokens"] == 5
    assert measured["non_reasoning_output_tokens"] == 7
    assert measured["reasoning_share"] == 5 / 12
    assert measured["total_cost"] == 0.25
    assert warnings == []

    missing = phase14._usage({"output_tokens": 12, "total_tokens": 12})
    assert missing["reasoning_tokens"] is None
    assert missing["non_reasoning_output_tokens"] is None
    assert missing["reasoning_share"] is None

    contradictory_warnings: list[str] = []
    contradictory = phase14._usage(
        {"output_tokens": 4, "reasoning_tokens": 5},
        warnings=contradictory_warnings,
    )
    assert contradictory["non_reasoning_output_tokens"] is None
    assert contradictory["reasoning_share"] is None
    assert contradictory_warnings == ["invalid_reasoning_token_accounting"]

    negative_warnings: list[str] = []
    negative = phase14._usage(
        {"output_tokens": -1},
        warnings=negative_warnings,
    )
    assert negative["non_reasoning_output_tokens"] is None
    assert negative_warnings == ["invalid_reasoning_token_accounting"]


def test_per_generation_usage_preserves_roles_phases_retries_and_acceptance() -> None:
    sample = _diagnostic_sample()
    warnings: list[str] = []
    generation_usage = phase14._per_generation_usage(sample, warnings=warnings)

    assert warnings == []
    assert len(generation_usage["candidate"]) == 1
    candidate = generation_usage["candidate"][0]
    assert candidate["role"] == "candidate"
    assert candidate["phase"] == "unknown"
    assert candidate["attempt_index"] == 1
    assert candidate["accepted"] is None
    assert candidate["reasoning_tokens"] == 2
    assert candidate["non_reasoning_output_tokens"] == 3

    stakeholder = generation_usage["stakeholder"]
    assert [(item["phase"], item["attempt_index"]) for item in stakeholder] == [
        ("plan", 1),
        ("plan", 2),
        ("realization", 1),
        ("realization", 2),
    ]
    assert [item["retry"] for item in stakeholder] == [False, True, False, True]
    assert [item["accepted"] for item in stakeholder] == [
        False,
        True,
        False,
        True,
    ]
    assert stakeholder[0]["visible_completion_chars"] == len("PRIVATE-PLAN-FIRST")
    assert stakeholder[0]["visible_completion_estimated_tokens"] is None
    assert stakeholder[0]["reasoning_tokens"] == 6
    assert stakeholder[0]["non_reasoning_output_tokens"] == 4

    split = phase14._stakeholder_attempt_usage_diagnostics(stakeholder)
    assert split["stakeholder_accepted_attempt_count"] == 2
    assert split["stakeholder_rejected_attempt_count"] == 2
    assert split["stakeholder_retry_attempt_count"] == 2
    assert split["stakeholder_reasoning_tokens_on_accepted_attempts"] == 45
    assert split["stakeholder_reasoning_tokens_on_rejected_attempts"] == 31
    assert split["stakeholder_reasoning_tokens_on_retry_attempts"] == 45
    assert split["stakeholder_output_tokens_on_rejected_attempts"] == 40


def test_unmarked_stakeholder_phases_use_candidate_boundary_for_new_response() -> None:
    events = [
        ModelEvent(role=None, completion="Question 1", usage=None),
        ModelEvent(role="stakeholder", completion='{"items": []}', usage=None),
        ModelEvent(role="stakeholder", completion="", usage=None),
        ModelEvent(role=None, completion="Question 2", usage=None),
        ModelEvent(role="stakeholder", completion="", usage=None),
        ModelEvent(
            role="stakeholder",
            completion='{"message": "Answer"}',
            usage=None,
        ),
    ]
    sample = _sample(events, accepted=False)
    groups = phase14._stakeholder_attempt_groups(sample)
    assert [(len(group["plan"]), len(group["realization"])) for group in groups] == [
        (1, 1),
        (1, 1),
    ]


def test_terminal_protocol_reason_precedes_incidental_tool_error() -> None:
    sample = _sample(
        [ToolEvent("invalid schema from a recovered tool call")],
        accepted=False,
        failure_reason="candidate_did_not_ask_question",
    )
    log = _log(sample, status="error")
    protocol = {
        "status": "incomplete",
        "failure_reason": "candidate_did_not_ask_question",
    }
    assert (
        phase14.classify_failure(cast(Any, log), sample, protocol, {})
        == "candidate_did_not_ask_question"
    )


def test_summary_and_aggregate_are_private_and_include_reasoning_accounting() -> None:
    sample = _diagnostic_sample()
    summary = phase14.summarize_eval_log_object(cast(Any, _log(sample)))
    run = summary["runs"][0]

    stakeholder_usage = run["usage"]["stakeholder"]
    assert stakeholder_usage["output_tokens"] == 100
    assert stakeholder_usage["reasoning_tokens"] == 76
    assert stakeholder_usage["non_reasoning_output_tokens"] == 24
    assert stakeholder_usage["reasoning_share"] == 0.76
    assert run["diagnostics"]["stakeholder_reasoning_tokens_on_accepted_attempts"] == 45
    assert run["diagnostics"]["stakeholder_reasoning_tokens_on_rejected_attempts"] == 31

    serialized = json.dumps(summary, ensure_ascii=False, sort_keys=True)
    assert "PRIVATE-CANDIDATE-COMPLETION" not in serialized
    assert "PRIVATE-PLAN-FIRST" not in serialized
    assert "PRIVATE-REALIZATION-ACCEPTED" not in serialized
    assert "PRIVATE-STAKEHOLDER-KNOWLEDGE" not in serialized
    assert "PRIVATE-KNOWLEDGE-MUST-NOT-LEAK" not in serialized
    assert "skn_private" not in serialized
    assert "visible_completion_chars" in serialized

    aggregate = phase14.aggregate_run_summaries([run, run])
    assert aggregate["usage"]["stakeholder"]["reasoning_tokens"] == 152
    assert aggregate["usage"]["stakeholder"]["non_reasoning_output_tokens"] == 48
    assert aggregate["usage"]["stakeholder"]["mean_reasoning_tokens"] == 76
    assert aggregate["total_stakeholder_reasoning_tokens_on_rejected_attempts"] == 62
    assert aggregate["mean_stakeholder_reasoning_tokens_on_rejected_attempts"] == 31
