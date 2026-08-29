"""Runtime-neutral canonical replay assets for the benchmark."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final

SEED9004_ID: Final = "seed9004"
SEED9004_FILES: Final = (
    "truth.json",
    "agent.json",
    "expected.json",
    "evaluation_context.json",
    "knowledge_coverage.json",
    "provenance.json",
)


def read_seed9004_text(filename: str) -> str:
    """Read one allow-listed seed 9004 asset from package resources."""
    if filename not in SEED9004_FILES:
        raise ValueError(f"unsupported seed 9004 asset: {filename!r}")
    asset_path = Path(__file__).resolve().parent / SEED9004_ID / filename
    return asset_path.read_text(encoding="utf-8")


def load_seed9004_payload(filename: str) -> dict[str, Any]:
    """Load one seed 9004 JSON asset as a fresh canonical payload."""
    try:
        value = json.loads(read_seed9004_text(filename))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"unable to load seed 9004 asset: {filename!r}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"seed 9004 asset is not a JSON object: {filename!r}")
    return value


__all__ = [
    "SEED9004_FILES",
    "SEED9004_ID",
    "load_seed9004_payload",
    "read_seed9004_text",
]
