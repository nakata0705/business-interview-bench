"""Registered Inspect task for the deterministic seed 9004 replay."""

# The workspace-level auxiliary resolver may not see the Inspect dev group.
# Project-level ``uv run pyright`` remains the authoritative adapter check.
# pyright: reportMissingImports=false

from __future__ import annotations

from inspect_ai import Task, task

from .dataset import seed9004_replay_dataset
from .scorer import primary_scorer
from .solver import seed9004_replay_solver


@task(name="seed9004_replay")
def seed9004_replay() -> Task:
    """Evaluate one packaged sample without model generation."""
    return Task(
        dataset=seed9004_replay_dataset(),
        solver=seed9004_replay_solver(),
        scorer=primary_scorer(),
        model="none",
        version=1,
    )


__all__ = ["seed9004_replay"]
