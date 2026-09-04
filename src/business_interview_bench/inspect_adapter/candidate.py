"""Candidate ModelOutput classification for the Inspect adapter.

Candidate generation semantics belong at the Inspect boundary.  The core
runtime receives only a provider-neutral terminal reason, while this module
keeps stop reasons, tool calls, and visible-output mechanics observable to the
safe diagnostics harness.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

CandidateOutcomeKind = Literal[
    "question",
    "tool_call",
    "empty_completion",
    "output_exhaustion",
    "provider_error",
    "invalid_tool_call",
]

_OUTPUT_LIMIT_STOP_REASONS = frozenset({"max_tokens", "model_length", "length"})


@dataclass(frozen=True, slots=True)
class CandidateGenerationOutcome:
    """Safe classification of one Candidate ``ModelOutput``."""

    outcome_kind: CandidateOutcomeKind
    stop_reason: str | None
    tool_call_count: int
    tool_names: tuple[str, ...]
    visible_completion_chars: int
    hit_output_limit: bool
    produced_question: bool


def _safe_stop_reason(output: object) -> str | None:
    try:
        value = getattr(output, "stop_reason", None)
    except (AttributeError, IndexError, TypeError):
        return None
    return value if isinstance(value, str) else None


def _safe_message(output: object) -> object | None:
    try:
        return getattr(output, "message", None)
    except (AttributeError, IndexError, TypeError):
        return None


def _safe_tool_calls(output: object) -> list[object]:
    message = _safe_message(output)
    try:
        calls = getattr(message, "tool_calls", None)
    except (AttributeError, TypeError):
        return []
    if isinstance(calls, (list, tuple)):
        return list(calls)
    return []


def _tool_name(call: object) -> str | None:
    try:
        function = getattr(call, "function", None)
    except (AttributeError, TypeError):
        return None
    return function if isinstance(function, str) and function else None


def _tool_call_is_invalid(call: object) -> bool:
    try:
        parse_error = getattr(call, "parse_error", None)
    except (AttributeError, TypeError):
        parse_error = None
    return bool(parse_error) or _tool_name(call) is None


def _visible_text(output: object) -> str:
    try:
        completion = getattr(output, "completion", None)
    except (AttributeError, TypeError):
        completion = None
    if isinstance(completion, str):
        return completion
    message = _safe_message(output)
    try:
        text = getattr(message, "text", None)
    except (AttributeError, TypeError):
        text = None
    return text if isinstance(text, str) else ""


def classify_candidate_output(output: object) -> CandidateGenerationOutcome:
    """Classify one generated Candidate output without retaining its content.

    Output-limit stop reasons take precedence over visible fragments and tool
    calls: a truncated generation is not a usable question/tool result.  A
    normally stopped blank output remains an ``empty_completion`` and is the
    only path that can become the true ``candidate_did_not_ask_question``
    terminal reason. Unknown or absent stop reasons are provider failures for
    blank outputs rather than evidence of deliberate no-question behavior.
    """
    stop_reason = _safe_stop_reason(output)
    calls = _safe_tool_calls(output)
    names = tuple(name for call in calls if (name := _tool_name(call)) is not None)
    visible_text = _visible_text(output)
    hit_output_limit = stop_reason in _OUTPUT_LIMIT_STOP_REASONS
    try:
        provider_error = bool(getattr(output, "error", None))
    except (AttributeError, TypeError):
        provider_error = False

    if provider_error or stop_reason == "content_filter":
        kind: CandidateOutcomeKind = "provider_error"
    elif hit_output_limit:
        kind = "output_exhaustion"
    elif stop_reason not in (None, "stop", "tool_calls"):
        # Unknown provider stop reasons must not be allowed to execute tools.
        kind = "provider_error"
    elif calls and any(_tool_call_is_invalid(call) for call in calls):
        kind = "invalid_tool_call"
    elif calls:
        kind = "tool_call"
    elif stop_reason == "stop" and visible_text.strip():
        kind = "question"
    elif stop_reason == "stop":
        kind = "empty_completion"
    else:
        # ``unknown`` and absent/malformed stop reasons are not evidence that
        # the Candidate deliberately declined to ask a question. Keep them in
        # the provider/generation-failure bucket instead.
        kind = "provider_error"

    return CandidateGenerationOutcome(
        outcome_kind=kind,
        stop_reason=stop_reason,
        tool_call_count=len(calls),
        tool_names=names,
        visible_completion_chars=len(visible_text),
        hit_output_limit=hit_output_limit,
        produced_question=kind == "question",
    )


__all__ = [
    "CandidateGenerationOutcome",
    "CandidateOutcomeKind",
    "classify_candidate_output",
]
