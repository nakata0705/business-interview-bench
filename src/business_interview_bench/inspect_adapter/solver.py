"""No-model deterministic replay solver."""

# The workspace-level auxiliary resolver may not see the Inspect dev group.
# Project-level ``uv run pyright`` remains the authoritative adapter check.
# pyright: reportMissingImports=false

from __future__ import annotations

from inspect_ai.solver import Generate, Solver, TaskState, solver

from .store import BusinessInterviewReplayStore, _load_seed9004_scoring_inputs


@solver(name="seed9004_replay_solver")
def seed9004_replay_solver() -> Solver:
    """Load and persist exact replay inputs without invoking a model."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        del generate  # required by Inspect's Solver protocol; replay never generates
        payload = _load_seed9004_scoring_inputs()
        replay_store = state.store_as(BusinessInterviewReplayStore)
        replay_store.agent = payload["agent"]
        replay_store.truth = payload["truth"]
        replay_store.evaluation_context = payload["evaluation_context"]
        replay_store.knowledge_coverage = payload["knowledge_coverage"]
        state.completed = True
        return state

    return solve


__all__ = ["seed9004_replay_solver"]
