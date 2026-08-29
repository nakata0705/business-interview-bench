"""Inspect scorer that delegates to the 41-field core evaluator."""

# The workspace-level auxiliary resolver may not see the Inspect dev group.
# Project-level ``uv run pyright`` remains the authoritative adapter check.
# pyright: reportMissingImports=false

from __future__ import annotations

from dataclasses import asdict
from typing import Any, cast

from inspect_ai.scorer import (
    Metric,
    SampleScore,
    Score,
    Scorer,
    Target,
    metric,
    scorer,
)
from inspect_ai.solver import TaskState

from business_interview.evaluation import evaluate_primary

from .store import (
    BusinessInterviewReplayStore,
    primary_evaluation_field_names,
    replay_inputs_from_store,
)


@metric(name="reconstruction_pass")
def reconstruction_pass_metric() -> Metric:
    """Expose the existing pass field as Inspect's single headline metric."""

    def calculate(scores: list[SampleScore]) -> float:
        if not scores:
            return 0.0
        values: list[float] = []
        for sample_score in scores:
            value = sample_score.score.value
            if not isinstance(value, dict) or "reconstruction_pass" not in value:
                raise ValueError(
                    "primary score is missing reconstruction_pass headline field"
                )
            headline = value["reconstruction_pass"]
            if isinstance(headline, bool):
                values.append(1.0 if headline else 0.0)
            elif isinstance(headline, int | float) and headline in (0, 1):
                # Some Inspect log/re-score paths validate dict values through
                # ``float`` before the original bool is exposed.
                values.append(1.0 if headline == 1 else 0.0)
            else:
                raise ValueError(
                    "reconstruction_pass headline must be boolean-like; "
                    f"got {headline!r} ({type(headline).__name__})"
                )
        return sum(values) / len(values)

    return calculate


@scorer(
    [reconstruction_pass_metric()],
    name="primary_scorer",
    headline_field="reconstruction_pass",
    score_contract="PrimaryEvaluation dataclass; no aggregate total",
)
def primary_scorer() -> Scorer:
    """Score exact Store inputs using only ``evaluate_primary``."""

    async def score(state: TaskState, target: Target) -> Score:
        replay_store = state.store_as(BusinessInterviewReplayStore)
        agent, truth, context, knowledge_coverage = replay_inputs_from_store(
            replay_store
        )
        result = evaluate_primary(agent, truth, context, knowledge_coverage)
        values: dict[str, Any] = asdict(result)
        field_names = primary_evaluation_field_names()
        if len(values) != len(field_names) or set(values) != set(field_names):
            raise ValueError(
                "evaluate_primary field contract changed: "
                f"expected {len(field_names)} fields {field_names!r}, "
                f"got {len(values)} fields {tuple(values)!r}"
            )
        return Score(
            value=cast(dict[str, str | int | float | bool | None], values),
            explanation=(
                "Authoritative business_interview.evaluation.evaluate_primary "
                "result; reconstruction_pass is the existing headline field."
            ),
            metadata={
                "field_count": len(field_names),
                "field_names": list(field_names),
                "headline_field": "reconstruction_pass",
                "aggregate_total": False,
            },
        )

    return score


__all__ = ["primary_scorer", "reconstruction_pass_metric"]
