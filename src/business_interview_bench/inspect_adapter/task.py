"""Registered Inspect task for the deterministic seed 9004 replay."""

# The workspace-level auxiliary resolver may not see the Inspect dev group.
# Project-level ``uv run pyright`` remains the authoritative adapter check.
# pyright: reportMissingImports=false

from __future__ import annotations

from inspect_ai import Task, task

from .dataset import seed9004_replay_dataset, seed9004_replay_metadata
from .scorer import primary_scorer
from .solver import seed9004_replay_solver


@task(
    name="seed9004_replay",
    version=1,
    tags=["business-interview", "deterministic-replay", "seed9004"],
)
def seed9004_replay() -> Task:
    """Evaluate one packaged sample without model generation."""
    metadata = seed9004_replay_metadata()
    metadata.update(
        {
            "adapter": "business_interview_bench.inspect_adapter",
            "headline_field": "reconstruction_pass",
            "score_contract": "PrimaryEvaluation dataclass; no aggregate total",
        }
    )
    return Task(
        dataset=seed9004_replay_dataset(),
        solver=seed9004_replay_solver(),
        scorer=primary_scorer(),
        model="none",
        metadata=metadata,
        version=1,
        epochs=1,
        fail_on_error=True,
    )


__all__ = ["seed9004_replay"]
