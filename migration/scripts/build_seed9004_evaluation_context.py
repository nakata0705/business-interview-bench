"""Build the tau2-free seed 9004 observation/evaluation context fixture.

The source checkout is read only while this migration script runs. It reads
only the persisted public ``observations``, ``db_messages_ledger``, and
``interview_complete`` values from the seed 9004 artifact, then drops fields
that the Phase 6 evaluator does not need. It never copies the full
conversation, Agent-visible observation markers, or private artifacts.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from build_seed9004_fixture import (
    _read_json,
    _safe_output_root,
    _source_context,
    _stable_json,
)

SOURCE_ARTIFACT = "artifacts/business_interview_real_llm/run_00_seed9004.json"
CONTEXT_FILE = "evaluation_context.json"


def _context_from_public(public: Mapping[str, Any]) -> dict[str, Any]:
    if public.get("seed") != 9004 or public.get("task_id") != "quotation_workflow_1":
        raise ValueError("public artifact is not seed 9004 quotation_workflow_1")

    raw_observations = public.get("observations")
    if not isinstance(raw_observations, list):
        raise ValueError("public.observations must be a list")
    raw_ledger = public.get("db_messages_ledger")
    if not isinstance(raw_ledger, list):
        raise ValueError("public.db_messages_ledger must be a list")
    protocol_completed = public.get("interview_complete")
    if not isinstance(protocol_completed, bool):
        raise ValueError("public.interview_complete must be a boolean")

    observations: list[dict[str, Any]] = []
    messages_by_turn: dict[str, dict[str, Any]] = {}
    for index, raw_observation in enumerate(raw_observations):
        if not isinstance(raw_observation, Mapping):
            raise ValueError(f"public.observations[{index}] must be an object")
        observation_id = raw_observation.get("id")
        text = raw_observation.get("text")
        turn = raw_observation.get("turn")
        if not isinstance(observation_id, str):
            raise ValueError(f"public.observations[{index}].id must be a string")
        if not isinstance(text, str):
            raise ValueError(f"public.observations[{index}].text must be a string")
        if not isinstance(turn, int) or isinstance(turn, bool):
            raise ValueError(f"public.observations[{index}].turn must be an integer")
        if turn < 0 or turn >= len(raw_ledger):
            raise ValueError(
                f"public.observations[{index}].turn {turn} is outside the ledger"
            )

        ledger_item = raw_ledger[turn]
        if not isinstance(ledger_item, Mapping):
            raise ValueError(f"public.db_messages_ledger[{turn}] must be an object")
        role = ledger_item.get("role")
        content = ledger_item.get("content")
        if not isinstance(role, str):
            raise ValueError(f"public.db_messages_ledger[{turn}].role must be a string")
        if content is not None and not isinstance(content, str):
            raise ValueError(
                f"public.db_messages_ledger[{turn}].content must be a string or null"
            )

        observations.append({"id": observation_id, "text": text, "turn": turn})
        messages_by_turn.setdefault(
            str(turn),
            {"role": role, "content": content},
        )

    return {
        "observations": observations,
        "messages_by_turn": messages_by_turn,
        "protocol_completed": protocol_completed,
    }


def build_context(*, source_root: Path, output_root: Path) -> Path:
    project_root = Path(__file__).resolve().parents[2]
    source_root = source_root.resolve()
    metadata = _read_json(project_root / "migration" / "source.json")
    expected_source_root = Path(str(metadata["source_repository_path"])).resolve()
    if source_root != expected_source_root:
        raise ValueError(
            "--source-root must match migration/source.json source_repository_path"
        )
    _source_context(project_root, source_root)

    output_root = _safe_output_root(project_root, output_root)
    output_path = (output_root / CONTEXT_FILE).resolve()
    if output_path.parent != output_root:
        raise ValueError("fixture context path must stay inside the output directory")
    public_path = source_root / SOURCE_ARTIFACT
    public = _read_json(public_path)
    context = _context_from_public(public)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(_stable_json(context), encoding="utf-8")
    return output_path


def _default_source_root() -> Path:
    return Path(__file__).resolve().parents[3] / "tau2-bench"


def _default_output_root() -> Path:
    return (
        Path(__file__).resolve().parents[2]
        / "src"
        / "business_interview"
        / "replay_data"
        / "seed9004"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=_default_source_root())
    parser.add_argument("--output", type=Path, default=_default_output_root())
    args = parser.parse_args(argv)
    try:
        output = build_context(
            source_root=args.source_root,
            output_root=args.output,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"seed9004 evaluation context generation failed: {exc}")
        return 1
    print(f"wrote seed9004 evaluation context to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
