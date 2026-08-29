"""No-model deterministic replay solver."""

# The workspace-level auxiliary resolver may not see the Inspect dev group.
# Project-level ``uv run pyright`` remains the authoritative adapter check.
# pyright: reportMissingImports=false

from __future__ import annotations

from inspect_ai.solver import Generate, Solver, TaskState, solver

from .store import BusinessInterviewReplayStore, load_seed9004_store_payload

_METADATA_KEYS = (
    "replay_case_id",
    "scenario_id",
    "source_repository",
    "source_branch",
    "source_commit_sha",
)


def _check_sample_metadata(state: TaskState, payload: dict[str, object]) -> None:
    for key in _METADATA_KEYS:
        expected = payload[key]
        actual = state.metadata.get(key)
        if actual != expected:
            raise ValueError(
                f"seed 9004 replay metadata {key!r} must be {expected!r}; "
                f"got {actual!r}"
            )


@solver(name="seed9004_replay_solver")
def seed9004_replay_solver() -> Solver:
    """Load and persist exact replay inputs without invoking a model."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        payload = load_seed9004_store_payload()
        _check_sample_metadata(state, payload)
        replay_store = state.store_as(BusinessInterviewReplayStore)
        for field_name, value in payload.items():
            setattr(replay_store, field_name, value)
        state.completed = True
        return state

    return solve


__all__ = ["seed9004_replay_solver"]
