"""Packaged seed 9004 replay dataset for Inspect."""

# The workspace-level auxiliary resolver may not see the Inspect dev group.
# Project-level ``uv run pyright`` remains the authoritative adapter check.
# pyright: reportMissingImports=false

from __future__ import annotations

from typing import Any

from inspect_ai.dataset import MemoryDataset, Sample

from business_interview.replay_data import load_seed9004_payload

SEED9004_REPLAY_CASE_ID = "seed9004"
SEED9004_SCENARIO_ID = "quotation_workflow_1"


def seed9004_replay_metadata() -> dict[str, Any]:
    provenance = load_seed9004_payload("provenance.json")
    source = provenance.get("source")
    if not isinstance(source, dict):
        raise ValueError("seed 9004 provenance has no source object")
    return {
        "replay_case_id": SEED9004_REPLAY_CASE_ID,
        "scenario_id": SEED9004_SCENARIO_ID,
        "replay_asset": "business_interview.replay_data/seed9004",
        "source_repository": source.get("repository", ""),
        "source_branch": source.get("branch", ""),
        "source_commit_sha": source.get("commit_sha", ""),
    }


def seed9004_replay_dataset() -> MemoryDataset:
    """Return the one-sample deterministic replay dataset."""
    return MemoryDataset(
        [
            Sample(
                id=SEED9004_REPLAY_CASE_ID,
                input="Business Interview seed 9004 deterministic replay.",
                target=SEED9004_REPLAY_CASE_ID,
                metadata=seed9004_replay_metadata(),
            )
        ],
        name=SEED9004_REPLAY_CASE_ID,
        location="business_interview.replay_data/seed9004",
    )


__all__ = [
    "SEED9004_REPLAY_CASE_ID",
    "SEED9004_SCENARIO_ID",
    "seed9004_replay_dataset",
    "seed9004_replay_metadata",
]
