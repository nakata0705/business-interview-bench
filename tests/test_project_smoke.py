"""Small, offline-only checks for the Phase 1 migration scaffold."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

import business_interview

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROVENANCE_PATH = PROJECT_ROOT / "migration" / "source.json"


def test_package_import_smoke() -> None:
    assert business_interview.__version__ == "0.1.0"


def test_source_provenance_has_required_metadata() -> None:
    provenance = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))

    assert provenance["source_repository"] == "nakata0705/tau2-bench"
    assert provenance["source_branch"] == "business-interview"
    assert re.fullmatch(r"[0-9a-f]{40}", provenance["source_head_sha"])
    assert provenance["migration_phase"] == "phase-1"
    assert isinstance(provenance["source_working_tree_clean"], bool)

    recorded_at = provenance["recorded_at"]
    assert isinstance(recorded_at, str)
    datetime.fromisoformat(recorded_at.replace("Z", "+00:00"))
