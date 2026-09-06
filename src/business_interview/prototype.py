"""Replayable, offline InterviewState compatibility examples.

Run from the repository root with::

    uv run python -m business_interview.prototype \
      --output-dir examples/interview_state/replays

The case files contain only public utterances and manually authored typed tool
calls.  They are compatibility examples, not automatic extraction results.
"""

# pyright: reportMissingImports=false

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from .interview_state import (
    InterviewHarness,
    InterviewState,
    ProcessStep,
    Utterance,
)
from .interview_tools import (
    InterviewToolExecutor,
    ToolName,
    ToolOutput,
    parse_tool_input,
    tool_schemas,
)

SourceKind = Literal["existing_public_fixture", "synthetic_partial", "synthetic_human"]


class _LabelledRecord(Protocol):
    id: str
    label: str


class ReplayUtterance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    speaker: str = Field(min_length=1)
    text: str = Field(min_length=1)


class ReplayOperation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tool: ToolName
    arguments: dict[str, Any] = Field(default_factory=dict)


class ReplayCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str = Field(
        min_length=1,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$",
    )
    title: str = Field(min_length=1)
    source_kind: SourceKind
    source_reference: str = Field(min_length=1)
    human_evaluation: Literal["not_applicable", "not_performed", "performed"]
    notes: str = Field(min_length=1)
    utterances: tuple[ReplayUtterance, ...]
    operations: tuple[ReplayOperation, ...]


class ReplayResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case: ReplayCase
    state: InterviewState
    receipts: tuple[ToolOutput, ...]


class ReplayError(RuntimeError):
    """Raised when a compatibility case cannot be replayed."""


def load_case(path: Path) -> ReplayCase:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReplayError(f"could not read replay case: {path}") from exc
    try:
        return ReplayCase.model_validate(payload)
    except ValueError as exc:
        raise ReplayError(f"invalid replay case: {path}: {exc}") from exc


def replay_case(case: ReplayCase) -> ReplayResult:
    """Run every case through the same harness and seven-operation executor."""
    harness = InterviewHarness()
    for item in case.utterances:
        harness.register_utterance(
            Utterance(id=item.id, speaker=item.speaker, text=item.text)
        )
    executor = InterviewToolExecutor(harness)
    receipts: list[ToolOutput] = []
    for index, operation in enumerate(case.operations, start=1):
        parsed = parse_tool_input(operation.tool, operation.arguments)
        handler = getattr(executor, operation.tool)
        receipt = handler(parsed)
        receipts.append(receipt)
        if not receipt.ok:
            message = "; ".join(item.message for item in receipt.errors)
            raise ReplayError(
                f"case {case.case_id!r} operation {index} "
                f"{operation.tool!r} failed: {message}"
            )
    return ReplayResult(case=case, state=executor.state, receipts=tuple(receipts))


def replay_case_file(path: Path) -> ReplayResult:
    return replay_case(load_case(path))


def _label_map(items: Sequence[_LabelledRecord]) -> dict[str, str]:
    return {item.id: item.label for item in items}


def _value(value: object) -> str:
    state = getattr(value, "state", None)
    if state == "value":
        return str(getattr(value, "value", getattr(value, "entity_id", "")))
    return str(state or value)


def _link(value: object, labels: dict[str, str]) -> str:
    state = getattr(value, "state", None)
    if state == "value":
        identifier = getattr(value, "entity_id", None)
        if not isinstance(identifier, str):
            return "value"
        return f"{labels.get(identifier, identifier)} [{identifier}]"
    return str(state)


def _flow_endpoint(endpoint: str, steps: dict[str, ProcessStep]) -> str:
    if endpoint in {"SOURCE", "SINK"}:
        return endpoint
    step = steps.get(endpoint)
    return f"{step.activity.value if step and step.activity.state == 'value' else endpoint} [{endpoint}]"


def render_report(result: ReplayResult) -> str:
    """Render the requested flow, systems, matrix, and uncertainty history."""
    state = result.state
    model = state.business_model
    steps = {item.id: item for item in model.process_steps}
    systems = _label_map(model.systems)
    data_types = _label_map(model.data_types)
    actors = _label_map(model.actors)
    lines = [
        f"# {result.case.case_id}: {result.case.title}",
        "",
        f"- source: `{result.case.source_kind}`",
        f"- source reference: `{result.case.source_reference}`",
        f"- human evaluation: `{result.case.human_evaluation}`",
        f"- note: {result.case.notes}",
        "",
        "## Current business flow",
        "",
    ]
    for flow in model.flows:
        condition = _value(flow.condition)
        suffix = "" if condition == "unset" else f" (when {condition})"
        lines.append(
            f"- `{flow.kind}`: {_flow_endpoint(flow.from_id, steps)} "
            f"→ {_flow_endpoint(flow.to_id, steps)}{suffix}"
        )
    if not model.flows:
        lines.append("- (no flow recorded)")

    lines.extend(["", "## Process steps", ""])
    for step in model.process_steps:
        activity = _value(step.activity)
        actor = _link(step.actor, actors)
        inputs = ", ".join(
            f"{data_types.get(item, item)} [{item}]" for item in step.inputs.entity_ids
        ) or str(step.inputs.state)
        outputs = ", ".join(
            f"{data_types.get(item, item)} [{item}]" for item in step.outputs.entity_ids
        ) or str(step.outputs.state)
        lines.append(
            f"- `{step.id}` {activity}; actor={actor}; inputs={inputs}; outputs={outputs}"
        )

    lines.extend(["", "## Systems", ""])
    for system in model.systems:
        lines.append(f"- `{system.id}`: {system.label} ({system.kind})")
    if not model.systems:
        lines.append("- (no named or manual system recorded)")

    lines.extend(
        [
            "",
            "## Process × system × data × CRUD",
            "",
            "| process | system | data type | CRUD |",
            "| --- | --- | --- | --- |",
        ]
    )
    for operation in model.data_operations:
        process = steps.get(operation.process_step_id)
        process_label = (
            _value(process.activity)
            if process is not None
            else operation.process_step_id
        )
        lines.append(
            f"| {process_label} [{operation.process_step_id}] | "
            f"{_link(operation.system, systems)} | "
            f"{_link(operation.data_type, data_types)} | `{operation.crud}` |"
        )
    if not model.data_operations:
        lines.append("| (none) | | | |")

    lines.extend(["", "## Evidence and claims", ""])
    for claim in state.claims:
        status = claim.status
        evidence = (
            ", ".join(
                f"{item.evidence_id}={item.utterance_id}[{item.start}:{item.end}]"
                for item in claim.evidence
            )
            or "(none)"
        )
        correction = f"; supersedes `{claim.supersedes}`" if claim.supersedes else ""
        lines.append(
            f"- `{claim.id}` [{status}] {claim.record_type}/{claim.target_id}/"
            f"{claim.predicate}: {_value(claim.value)}; evidence={evidence}{correction}"
        )

    lines.extend(["", "## Open questions", ""])
    for question in state.open_questions:
        lines.append(
            f"- `{question.id}` [{question.status}] {question.text} "
            f"(target: {', '.join(question.target_ids)})"
        )
    if not state.open_questions:
        lines.append("- (none)")

    lines.extend(["", "## Contradictions", ""])
    for contradiction in state.contradictions:
        lines.append(
            f"- `{contradiction.id}` [{contradiction.status}]: "
            f"{', '.join(contradiction.claim_ids)}"
        )
    if not state.contradictions:
        lines.append("- (none)")

    lines.extend(["", "## Corrections", ""])
    corrections = [item for item in state.claims if item.supersedes]
    for claim in corrections:
        lines.append(
            f"- `{claim.supersedes}` → `{claim.id}`; old claim is rejected, "
            f"new value is {_value(claim.value)}"
        )
    if not corrections:
        lines.append("- (none)")

    lines.extend(
        [
            "",
            "## Completion",
            "",
            f"- status: `{state.completion.status}`",
            f"- termination reason: `{state.completion.termination_reason}`",
            f"- unresolved: {', '.join(state.completion.unresolved_question_ids) or '(none)'}",
            f"- stakeholder confirmed: `{state.completion.stakeholder_confirmed}`",
            f"- content completeness: `{state.completion.content_completeness}`",
        ]
    )
    return "\n".join(lines) + "\n"


def _safe_output_path(output_root: Path, filename: str) -> Path:
    candidate = (output_root / filename).resolve()
    if candidate.parent != output_root:
        raise ReplayError(f"unsafe replay output filename: {filename!r}")
    return candidate


def write_replay_outputs(
    case_paths: Sequence[Path], output_dir: Path
) -> tuple[ReplayResult, ...]:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_root = output_dir.resolve()
    results: list[ReplayResult] = []
    for path in case_paths:
        result = replay_case_file(path)
        results.append(result)
        stem = result.case.case_id
        state_path = _safe_output_path(output_root, f"{stem}.state.json")
        report_path = _safe_output_path(output_root, f"{stem}.report.md")
        state_path.write_text(
            json.dumps(
                result.state.model_dump(mode="json"),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        report_path.write_text(render_report(result), encoding="utf-8")
    _safe_output_path(output_root, "tool-schemas.json").write_text(
        json.dumps(tool_schemas(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    manifest = {
        "schema_version": "business_interview.prototype_replay.v1",
        "tool_schema_file": "tool-schemas.json",
        "cases": [
            {
                "case_id": result.case.case_id,
                "source_kind": result.case.source_kind,
                "state_file": f"{result.case.case_id}.state.json",
                "report_file": f"{result.case.case_id}.report.md",
                "operation_count": len(result.receipts),
                "completion_status": result.state.completion.status,
            }
            for result in results
        ],
    }
    _safe_output_path(output_root, "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return tuple(results)


def _default_case_dir() -> Path:
    return Path("examples/interview_state/cases")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-dir", type=Path, default=_default_case_dir())
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("examples/interview_state/replays"),
    )
    parser.add_argument("--case-id", action="append", default=[])
    args = parser.parse_args(argv)
    paths = sorted(args.case_dir.glob("*.json"))
    if args.case_id:
        wanted = set(args.case_id)
        paths = [path for path in paths if path.stem in wanted]
    if not paths:
        parser.error("no replay case files found")
    results = write_replay_outputs(paths, args.output_dir)
    for result in results:
        print(
            f"{result.case.case_id}: {len(result.receipts)} operations; "
            f"completion={result.state.completion.status}; "
            f"source={result.case.source_kind}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ReplayCase",
    "ReplayError",
    "ReplayOperation",
    "ReplayResult",
    "ReplayUtterance",
    "load_case",
    "main",
    "render_report",
    "replay_case",
    "replay_case_file",
    "write_replay_outputs",
]
