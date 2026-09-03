"""Thin Inspect adapter for one two-call stakeholder response."""

# The workspace-level auxiliary resolver may not see the Inspect dev group.
# Project-level ``uv run pyright`` remains the authoritative adapter check.
# pyright: reportMissingImports=false

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from inspect_ai.model import (
    ChatMessage,
    ChatMessageSystem,
    ChatMessageUser,
    GenerateConfig,
    Model,
    ModelOutput,
    ResponseSchema,
    get_model,
)
from inspect_ai.util import JSONSchema

from business_interview.runtime import SemanticLedger
from business_interview.scenarios import StakeholderPrompt
from business_interview.stakeholders.knowledge import (
    StakeholderKnowledge,
    validate_stakeholder_knowledge,
)
from business_interview.stakeholders.prompting import render_knowledge_prompt
from business_interview.stakeholders.response import (
    ResponseParseError,
    ResponseValidationError,
    SemanticResponsePlan,
    StakeholderResponse,
    parse_semantic_response_plan,
    parse_stakeholder_response,
    validate_response_plan,
    validate_stakeholder_response,
    validate_terminology_provenance,
)

_DEFAULT_MAX_ATTEMPTS = 3
_PLAN_INSTRUCTION = (
    "Choose only the semantic assertions supported by the private knowledge. "
    'Return only JSON in this shape: {"items": [{"semantic_id": "...", '
    '"mode": "value|absent|dont_know|exists|mention"}]} . '
    "Use local IDs exactly as shown. Plan only what you will actually name or "
    "realize in the answer; keep the plan focused on the question. An empty "
    "plan is valid only when the answer carries no knowledge."
)
_REALIZATION_INSTRUCTION = (
    "Return only JSON in this shape: {"
    '"message": "...", "annotations": [{"semantic_id": "...", '
    '"mode": "...", "quote": "...", "occurrence": 0}], '
    '"alignments": [], "terminology": [{"semantic_id": "...", '
    '"proposed_term": "...", "proposal_turn": 0, '
    '"proposal_quote": "...", "proposal_occurrence": 0, '
    '"quote": "...", "occurrence": 0}]}. '
    "Naturally express every item in the validated plan, annotate each item "
    "with the same semantic_id and mode and a non-empty exact message span, "
    "add no unplanned business assertion, and never put local IDs in message. "
    "For absent or unknown items, use a short natural phrase expressing that "
    "state and quote that phrase; never use an empty quote. When describing "
    "relations, include their planned relation span too. Include terminology "
    "only when the assistant history contains the exact proposed term and "
    "preserve both proposal and agreement provenance fields."
)


def _inspect_json_schema(
    model: type[SemanticResponsePlan] | type[StakeholderResponse],
) -> JSONSchema:
    """Inline Pydantic definitions into Inspect's portable JSONSchema type."""
    raw_schema = model.model_json_schema()
    definitions = raw_schema.get("$defs", {})
    allowed = {
        "type",
        "format",
        "description",
        "default",
        "enum",
        "items",
        "properties",
        "additionalProperties",
        "anyOf",
        "required",
        "pattern",
        "minLength",
        "maxLength",
        "minimum",
        "maximum",
        "examples",
    }

    def inline(node: object) -> dict[str, object]:
        if not isinstance(node, Mapping):
            return {}
        reference = node.get("$ref")
        if isinstance(reference, str) and reference.startswith("#/$defs/"):
            definition = definitions.get(reference.removeprefix("#/$defs/"))
            if isinstance(definition, Mapping):
                return inline(definition)
        result: dict[str, object] = {}
        for key, value in node.items():
            if key not in allowed:
                continue
            if key == "properties" and isinstance(value, Mapping):
                result[key] = {
                    str(name): inline(property_schema)
                    for name, property_schema in value.items()
                }
            elif key == "items":
                result[key] = inline(value)
            elif key == "anyOf" and isinstance(value, list):
                result[key] = [inline(option) for option in value]
            elif key == "additionalProperties" and isinstance(value, Mapping):
                result[key] = inline(value)
            else:
                result[key] = value
        return result

    return JSONSchema.model_validate(inline(raw_schema))


# Inspect passes these schemas to OpenAI-compatible providers as the native
# ``response_format=json_schema`` request field.  ``strict=False`` keeps the
# defaults for the optional sidecar arrays provider-compatible; deterministic
# semantic validation below remains authoritative after parsing.
_PLAN_RESPONSE_SCHEMA = ResponseSchema(
    name="semantic_response_plan",
    json_schema=_inspect_json_schema(SemanticResponsePlan),
    description="A private knowledge-backed plan of stakeholder assertions.",
    strict=False,
)
_RESPONSE_RESPONSE_SCHEMA = ResponseSchema(
    name="stakeholder_response",
    json_schema=_inspect_json_schema(StakeholderResponse),
    description="A public stakeholder message with its private sidecar.",
    strict=False,
)

StakeholderFailureKind = Literal[
    "structural", "semantic", "output_exhaustion", "provider"
]
StakeholderFailurePhase = Literal["plan", "realization"]


@dataclass(slots=True)
class StakeholderAttemptDiagnostics:
    """Safe counters for bounded stakeholder output attempts.

    These fields describe response mechanics only.  They deliberately contain
    no model output, prompt text, local IDs, or knowledge content.
    """

    what_structural_rejections: int = 0
    what_semantic_rejections: int = 0
    how_structural_rejections: int = 0
    how_semantic_rejections: int = 0
    output_exhaustion_count: int = 0
    provider_error_count: int = 0
    retry_count: int = 0

    def record(
        self,
        phase: StakeholderFailurePhase,
        kind: StakeholderFailureKind,
        *,
        will_retry: bool,
    ) -> None:
        if kind == "provider":
            self.provider_error_count += 1
            return
        if kind == "output_exhaustion":
            self.output_exhaustion_count += 1
            if will_retry:
                self.retry_count += 1
            return
        if phase == "plan":
            if kind == "structural":
                self.what_structural_rejections += 1
            else:
                self.what_semantic_rejections += 1
        elif kind == "structural":
            self.how_structural_rejections += 1
        else:
            self.how_semantic_rejections += 1
        if will_retry:
            self.retry_count += 1

    def merged(
        self, other: StakeholderAttemptDiagnostics
    ) -> StakeholderAttemptDiagnostics:
        return StakeholderAttemptDiagnostics(
            what_structural_rejections=(
                self.what_structural_rejections + other.what_structural_rejections
            ),
            what_semantic_rejections=(
                self.what_semantic_rejections + other.what_semantic_rejections
            ),
            how_structural_rejections=(
                self.how_structural_rejections + other.how_structural_rejections
            ),
            how_semantic_rejections=(
                self.how_semantic_rejections + other.how_semantic_rejections
            ),
            output_exhaustion_count=(
                self.output_exhaustion_count + other.output_exhaustion_count
            ),
            provider_error_count=(
                self.provider_error_count + other.provider_error_count
            ),
            retry_count=self.retry_count + other.retry_count,
        )

    def as_dict(self) -> dict[str, int]:
        return {
            "what_structural_rejections": self.what_structural_rejections,
            "what_semantic_rejections": self.what_semantic_rejections,
            "how_structural_rejections": self.how_structural_rejections,
            "how_semantic_rejections": self.how_semantic_rejections,
            "output_exhaustion_count": self.output_exhaustion_count,
            "provider_error_count": self.provider_error_count,
            "retry_count": self.retry_count,
        }


def _phase_name(phase: StakeholderFailurePhase) -> str:
    return "what" if phase == "plan" else "how"


class StakeholderResponseError(ValueError):
    """Raised when bounded stakeholder output cannot produce a valid response."""

    def __init__(
        self,
        message: str,
        *,
        phase: StakeholderFailurePhase | None = None,
        failure_kind: StakeholderFailureKind | None = None,
        failure_reason: str | None = None,
        diagnostics: StakeholderAttemptDiagnostics | None = None,
        attempts: int | None = None,
        retry_exhausted: bool = True,
    ) -> None:
        super().__init__(message)
        self.phase = phase
        self.failure_kind = failure_kind
        self.failure_reason = failure_reason
        self.diagnostics = diagnostics
        self.attempts = attempts
        self.retry_exhausted = retry_exhausted


class StakeholderGenerationError(StakeholderResponseError):
    """Raised for provider/generation failures, never semantic retry failures."""

    def __init__(self, phase: StakeholderFailurePhase) -> None:
        super().__init__(
            f"stakeholder {phase} provider/generation failure",
            phase=phase,
            failure_kind="provider",
            failure_reason=f"stakeholder_{_phase_name(phase)}_provider_generation_failure",
            diagnostics=StakeholderAttemptDiagnostics(),
            attempts=1,
            retry_exhausted=False,
        )


class _StakeholderAttemptFailure(ValueError):
    phase: StakeholderFailurePhase
    kind: Literal["structural", "semantic", "output_exhaustion"]
    reason: str

    def __init__(
        self,
        phase: StakeholderFailurePhase,
        kind: Literal["structural", "semantic", "output_exhaustion"],
        reason: str,
    ) -> None:
        super().__init__(reason)
        self.phase = phase
        self.kind = kind
        self.reason = reason


@dataclass(frozen=True, slots=True)
class StakeholderTurn:
    """The validated private WHAT/HOW pair for one public response."""

    plan: SemanticResponsePlan
    response: StakeholderResponse
    diagnostics: StakeholderAttemptDiagnostics = field(
        default_factory=StakeholderAttemptDiagnostics
    )


def _render_scenario_prompt(prompt: StakeholderPrompt | str | None) -> str:
    """Render public scenario behavior instructions without evaluator data."""
    if prompt is None:
        return ""
    if isinstance(prompt, str):
        if not prompt.strip():
            raise ValueError("stakeholder_prompt must not be blank")
        return prompt
    return (
        "Scenario behavior instructions (public/business behavior only):\n"
        f"Persona:\n{prompt.persona}\n\n"
        f"Reason for call:\n{prompt.reason_for_call}\n\n"
        f"Task instructions:\n{prompt.task_instructions}"
    )


def _model_input(
    conversation: Sequence[ChatMessage],
    system_context: str,
    instruction: str,
) -> list[ChatMessage]:
    return [
        ChatMessageSystem(content=system_context),
        *conversation,
        ChatMessageUser(content=instruction),
    ]


def _validate_prior_ledger(
    knowledge: StakeholderKnowledge,
    conversation: Sequence[ChatMessage],
    ledger: SemanticLedger | None,
) -> None:
    """Reject private terminology that lacks both sides of its provenance."""
    if ledger is None:
        return
    for entry in ledger.entries:
        if not entry.terminology:
            continue
        validate_terminology_provenance(
            entry.terminology,
            conversation,
            response_public_message_turn=entry.public_message_turn,
        )
        if entry.public_message_turn >= len(conversation):
            raise ValueError(
                "prior terminology agreement message is not in conversation history"
            )
        message = conversation[entry.public_message_turn]
        if message.role != "user":
            raise ValueError(
                "prior terminology agreement must target a stakeholder message"
            )
        text = message.text
        for index, event in enumerate(entry.terminology):
            try:
                resolved = knowledge.resolve(event.semantic_id)
            except ValueError as exc:
                raise ValueError(
                    f"prior terminology {index} has an unknown stakeholder concept"
                ) from exc
            if resolved.kind != "concept":
                raise ValueError(
                    f"prior terminology {index} does not target a stakeholder concept"
                )
            start = -1
            for _occurrence in range(event.occurrence + 1):
                start = text.find(event.quote, start + 1)
                if start < 0:
                    raise ValueError(
                        f"prior terminology {index} agreement quote is not "
                        "an exact stakeholder message span"
                    )


def _stakeholder_system_context(
    prompt: StakeholderPrompt | str | None,
    knowledge: StakeholderKnowledge,
    conversation: Sequence[ChatMessage],
    prior_ledger: SemanticLedger | None,
) -> str:
    _validate_prior_ledger(knowledge, conversation, prior_ledger)
    parts = [
        part
        for part in (
            _render_scenario_prompt(prompt),
            render_knowledge_prompt(knowledge),
            _prior_ledger_prompt(prior_ledger),
        )
        if part
    ]
    return "\n\n".join(parts)


def _prior_ledger_prompt(ledger: SemanticLedger | None) -> str:
    """Render prior validated sidecar events for the stakeholder only."""
    if ledger is None:
        return ""
    events = [
        {
            "observation_id": entry.observation_id,
            "public_message_turn": entry.public_message_turn,
            "annotations": [item.model_dump(mode="json") for item in entry.annotations],
            "alignments": [item.model_dump(mode="json") for item in entry.alignments],
            "terminology": [item.model_dump(mode="json") for item in entry.terminology],
        }
        for entry in ledger.entries
        if entry.annotations or entry.alignments or entry.terminology
    ]
    if not events:
        return ""
    payload = json.dumps(events, ensure_ascii=False, sort_keys=True)
    return (
        "\nPreviously validated private sidecar events for this stakeholder "
        "session (do not reveal their IDs or JSON):\n"
        f"{payload}\n"
        "Use these only to keep confirmed terminology consistent; do not add "
        "facts that are not in the current private knowledge."
    )


def _extract_json_object(content: str) -> str:
    """Extract one balanced JSON object without repairing its semantics.

    Native structured output is the primary path.  This small compatibility
    parser only tolerates common provider wrappers (a JSON fence or a short
    prefix/suffix); Pydantic parsing and domain validation remain strict.
    """
    text = content.strip()
    fenced = re.search(
        r"```(?:json)?\s*(.*?)```", text, flags=re.IGNORECASE | re.DOTALL
    )
    if fenced is not None:
        text = fenced.group(1).strip()
    parse_succeeded = True
    try:
        json.loads(text)
    except (TypeError, ValueError):
        parse_succeeded = False
    if parse_succeeded:
        return text

    start = text.find("{")
    if start < 0:
        return text
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        character = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return text


def _safe_schema_reason(error: ResponseParseError) -> str:
    cause = error.__cause__
    if isinstance(cause, json.JSONDecodeError):
        return "malformed JSON"
    errors = getattr(cause, "errors", None)
    if callable(errors):
        try:
            raw_entries = errors()
        except Exception:
            raw_entries = []
        entries = raw_entries if isinstance(raw_entries, list) else []
        details: list[str] = []
        for entry in entries[:3]:
            if not isinstance(entry, dict):
                continue
            location = entry.get("loc", ())
            if isinstance(location, (tuple, list)):
                location_text = ".".join(str(part) for part in location)
            else:
                location_text = str(location)
            message = " ".join(str(entry.get("msg", "invalid field")).split())
            details.append(f"{location_text or 'response'}: {message[:100]}")
        if details:
            return "schema mismatch (" + "; ".join(details) + ")"
    return "invalid JSON object for the requested response schema"


def _safe_semantic_reason(error: ResponseValidationError) -> str:
    text = str(error).lower()
    if "missing planned semantic items" in text:
        return "every item in the validated plan must be realized"
    if "unplanned semantic item" in text:
        return "do not add assertions outside the validated plan"
    if "exact span" in text or "quote" in text:
        return "each quote must be an exact message span with the correct occurrence"
    if "terminology" in text or "proposal" in text:
        return "terminology entries must preserve validated proposal provenance"
    if "private identifier" in text:
        return "never place private local identifiers in the public message"
    if "mode" in text or "requires" in text:
        return "use the mode required by the validated stakeholder knowledge"
    return "response did not satisfy the validated semantic contract"


def _contract_failure(
    phase: StakeholderFailurePhase,
    error: ResponseParseError | ResponseValidationError,
) -> _StakeholderAttemptFailure:
    if isinstance(error, ResponseParseError):
        return _StakeholderAttemptFailure(
            phase,
            "structural",
            _safe_schema_reason(error),
        )
    return _StakeholderAttemptFailure(
        phase,
        "semantic",
        _safe_semantic_reason(error),
    )


def _output_attempt_failure(
    output: ModelOutput,
    phase: StakeholderFailurePhase,
) -> _StakeholderAttemptFailure | None:
    if output.error:
        raise StakeholderGenerationError(phase)
    if output.empty:
        return _StakeholderAttemptFailure(
            phase,
            "structural",
            "model returned no response choice",
        )
    try:
        stop_reason = output.stop_reason
    except (IndexError, AttributeError):
        return _StakeholderAttemptFailure(
            phase,
            "structural",
            "model returned no visible response",
        )
    if stop_reason in {"max_tokens", "model_length", "length"}:
        return _StakeholderAttemptFailure(
            phase,
            "output_exhaustion",
            "model output reached its token limit before a complete JSON object",
        )
    if output.completion.strip():
        return None
    if stop_reason == "content_filter":
        raise StakeholderGenerationError(phase)
    return _StakeholderAttemptFailure(
        phase,
        "structural",
        "model returned an empty visible response",
    )


def _retry_instruction(
    instruction: str,
    error: _StakeholderAttemptFailure | None,
) -> str:
    if error is None:
        return instruction
    return (
        f"{instruction}\nPrevious output rejected: [{error.kind}] {error.reason} "
        "Return one corrected JSON object only; do not add commentary."
    )


def _terminal_failure_reason(
    phase: StakeholderFailurePhase,
    kind: Literal["structural", "semantic", "output_exhaustion"],
) -> str:
    return f"stakeholder_{_phase_name(phase)}_{kind}_exhausted"


def _record_attempt_failure(
    diagnostics: StakeholderAttemptDiagnostics,
    failure: _StakeholderAttemptFailure,
    *,
    will_retry: bool,
) -> None:
    diagnostics.record(failure.phase, failure.kind, will_retry=will_retry)


def _merge_error_diagnostics(
    error: StakeholderResponseError,
    prior: StakeholderAttemptDiagnostics,
) -> None:
    if error.diagnostics is None:
        error.diagnostics = prior
    else:
        error.diagnostics = prior.merged(error.diagnostics)


def _attempts_are_positive(plan_attempts: int, realization_attempts: int) -> None:
    if plan_attempts < 1 or realization_attempts < 1:
        raise ValueError("retry attempt limits must be positive")


async def _generate_model_output(
    model: Model,
    messages: list[ChatMessage],
    schema: ResponseSchema,
    phase: StakeholderFailurePhase,
) -> ModelOutput:
    """Call Inspect with native structured output and classify provider errors."""
    try:
        return await model.generate(
            messages,
            config=GenerateConfig(response_schema=schema),
        )
    except StakeholderGenerationError:
        raise
    except Exception as exc:
        raise StakeholderGenerationError(phase) from exc


def _record_provider_failure(
    error: StakeholderGenerationError,
    diagnostics: StakeholderAttemptDiagnostics,
) -> None:
    diagnostics.provider_error_count += 1
    error.diagnostics = diagnostics


async def _generate_plan(
    model: Model,
    conversation: Sequence[ChatMessage],
    knowledge: StakeholderKnowledge,
    system_context: str,
    max_attempts: int,
) -> tuple[SemanticResponsePlan, StakeholderAttemptDiagnostics]:
    diagnostics = StakeholderAttemptDiagnostics()
    failure: _StakeholderAttemptFailure | None = None
    for _attempt in range(max_attempts):
        try:
            output = await _generate_model_output(
                model,
                _model_input(
                    conversation,
                    system_context,
                    _retry_instruction(_PLAN_INSTRUCTION, failure),
                ),
                _PLAN_RESPONSE_SCHEMA,
                "plan",
            )
            output_failure = _output_attempt_failure(output, "plan")
            if output_failure is not None:
                raise output_failure
            plan = parse_semantic_response_plan(_extract_json_object(output.completion))
            return validate_response_plan(knowledge, plan), diagnostics
        except StakeholderGenerationError as exc:
            _record_provider_failure(exc, diagnostics)
            raise
        except _StakeholderAttemptFailure as exc:
            failure = exc
            _record_attempt_failure(
                diagnostics, failure, will_retry=_attempt < max_attempts - 1
            )
        except (ResponseParseError, ResponseValidationError) as exc:
            failure = _contract_failure("plan", exc)
            _record_attempt_failure(
                diagnostics, failure, will_retry=_attempt < max_attempts - 1
            )

    if failure is None:
        raise StakeholderResponseError(
            "stakeholder response plan had no attempts",
            phase="plan",
            failure_reason="stakeholder_what_no_attempts",
            diagnostics=diagnostics,
            attempts=max_attempts,
        )
    raise StakeholderResponseError(
        f"stakeholder response plan rejected after {max_attempts} attempts: "
        f"{failure.reason}",
        phase="plan",
        failure_kind=failure.kind,
        failure_reason=_terminal_failure_reason("plan", failure.kind),
        diagnostics=diagnostics,
        attempts=max_attempts,
    ) from failure


async def _realize_response(
    model: Model,
    conversation: Sequence[ChatMessage],
    knowledge: StakeholderKnowledge,
    system_context: str,
    plan: SemanticResponsePlan,
    max_attempts: int,
) -> tuple[StakeholderResponse, StakeholderAttemptDiagnostics]:
    diagnostics = StakeholderAttemptDiagnostics()
    failure: _StakeholderAttemptFailure | None = None
    plan_json = json.dumps(plan.model_dump(mode="json"), ensure_ascii=False)
    instruction = f"{_REALIZATION_INSTRUCTION}\nValidated private plan: {plan_json}"
    for _attempt in range(max_attempts):
        try:
            output = await _generate_model_output(
                model,
                _model_input(
                    conversation,
                    system_context,
                    _retry_instruction(instruction, failure),
                ),
                _RESPONSE_RESPONSE_SCHEMA,
                "realization",
            )
            output_failure = _output_attempt_failure(output, "realization")
            if output_failure is not None:
                raise output_failure
            response = parse_stakeholder_response(
                _extract_json_object(output.completion)
            )
            return (
                validate_stakeholder_response(
                    knowledge,
                    plan,
                    response,
                    interviewer_messages=conversation,
                    response_public_message_turn=len(conversation),
                ),
                diagnostics,
            )
        except StakeholderGenerationError as exc:
            _record_provider_failure(exc, diagnostics)
            raise
        except _StakeholderAttemptFailure as exc:
            failure = exc
            _record_attempt_failure(
                diagnostics, failure, will_retry=_attempt < max_attempts - 1
            )
        except (ResponseParseError, ResponseValidationError) as exc:
            failure = _contract_failure("realization", exc)
            _record_attempt_failure(
                diagnostics, failure, will_retry=_attempt < max_attempts - 1
            )

    if failure is None:
        raise StakeholderResponseError(
            "stakeholder response had no attempts",
            phase="realization",
            failure_reason="stakeholder_how_no_attempts",
            diagnostics=diagnostics,
            attempts=max_attempts,
        )
    raise StakeholderResponseError(
        f"stakeholder response rejected after {max_attempts} attempts: "
        f"{failure.reason}",
        phase="realization",
        failure_kind=failure.kind,
        failure_reason=_terminal_failure_reason("realization", failure.kind),
        diagnostics=diagnostics,
        attempts=max_attempts,
    ) from failure


async def invoke_stakeholder_response_with_plan(
    conversation: Sequence[ChatMessage],
    knowledge: StakeholderKnowledge,
    *,
    stakeholder_prompt: StakeholderPrompt | str | None = None,
    prior_ledger: SemanticLedger | None = None,
    max_plan_attempts: int = _DEFAULT_MAX_ATTEMPTS,
    max_realization_attempts: int = _DEFAULT_MAX_ATTEMPTS,
) -> StakeholderTurn:
    """Generate and return one validated private plan plus public response."""
    _attempts_are_positive(max_plan_attempts, max_realization_attempts)
    validate_stakeholder_knowledge(knowledge)
    model = get_model(role="stakeholder", required=True)
    system_context = _stakeholder_system_context(
        stakeholder_prompt,
        knowledge,
        conversation,
        prior_ledger,
    )
    plan, plan_diagnostics = await _generate_plan(
        model,
        conversation,
        knowledge,
        system_context,
        max_plan_attempts,
    )
    try:
        response, response_diagnostics = await _realize_response(
            model,
            conversation,
            knowledge,
            system_context,
            plan,
            max_realization_attempts,
        )
    except StakeholderResponseError as exc:
        _merge_error_diagnostics(exc, plan_diagnostics)
        raise
    return StakeholderTurn(
        plan=plan,
        response=response,
        diagnostics=plan_diagnostics.merged(response_diagnostics),
    )


async def invoke_stakeholder_response(
    conversation: Sequence[ChatMessage],
    knowledge: StakeholderKnowledge,
    *,
    stakeholder_prompt: StakeholderPrompt | str | None = None,
    prior_ledger: SemanticLedger | None = None,
    max_plan_attempts: int = _DEFAULT_MAX_ATTEMPTS,
    max_realization_attempts: int = _DEFAULT_MAX_ATTEMPTS,
) -> StakeholderResponse:
    """Generate one validated stakeholder response using exactly two phases.

    The stakeholder role is required explicitly; the current candidate model
    is never used as an implicit fallback. Provider errors are allowed to
    propagate separately from bounded semantic-output retries.
    """
    turn = await invoke_stakeholder_response_with_plan(
        conversation,
        knowledge,
        stakeholder_prompt=stakeholder_prompt,
        prior_ledger=prior_ledger,
        max_plan_attempts=max_plan_attempts,
        max_realization_attempts=max_realization_attempts,
    )
    return turn.response


__all__ = [
    "StakeholderAttemptDiagnostics",
    "StakeholderGenerationError",
    "StakeholderResponseError",
    "StakeholderTurn",
    "invoke_stakeholder_response",
    "invoke_stakeholder_response_with_plan",
]
