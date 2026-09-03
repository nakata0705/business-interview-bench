"""Pure stakeholder response contracts and deterministic semantic validation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal

from pydantic import Field, field_validator

from .addressing import (
    ResolvedSemanticAddress,
    SemanticAddressError,
    resolve_semantic_address,
)
from .base import _DeeplyImmutableModel
from .knowledge import (
    StakeholderKnowledge,
    StakeholderKnowledgeGraph,
    is_dont_know,
)

SemanticMode = Literal["value", "absent", "dont_know", "exists", "mention"]
AlignmentAct = Literal["confirm", "partial", "unknown", "dispute"]
ResponseValidationCode = Literal[
    "unresolvable_semantic_address",
    "canonical_mode_mismatch",
    "realization_semantic_mismatch",
]


class ResponseParseError(ValueError):
    """Raised when model output is not valid JSON for a response contract."""


class ResponseValidationError(ValueError):
    """Raised when a response contract contradicts stakeholder knowledge."""

    code: ResponseValidationCode

    def __init__(
        self,
        message: str,
        *,
        code: ResponseValidationCode = "realization_semantic_mismatch",
    ) -> None:
        super().__init__(message)
        self.code: ResponseValidationCode = code


class PlannedResponseItem(_DeeplyImmutableModel):
    """One knowledge-backed semantic assertion in a response plan."""

    semantic_id: str = Field(min_length=1)
    mode: SemanticMode

    @field_validator("semantic_id")
    @classmethod
    def _semantic_id_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("semantic_id must not be blank")
        return value


class SemanticResponsePlan(_DeeplyImmutableModel):
    """The private WHAT to convey before natural-language realization."""

    items: tuple[PlannedResponseItem, ...] = Field(default_factory=tuple)


class SemanticAnnotation(_DeeplyImmutableModel):
    """One private exact-span assertion in a realized stakeholder message."""

    semantic_id: str = Field(min_length=1)
    mode: SemanticMode
    quote: str = Field(min_length=1)
    occurrence: int = Field(default=0, ge=0)

    @field_validator("semantic_id", "quote")
    @classmethod
    def _text_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("semantic_id and quote must not be blank")
        return value


class ConceptAlignmentAssertion(_DeeplyImmutableModel):
    """A private concept-identity dialogue act anchored to a message span."""

    semantic_id: str = Field(min_length=1)
    quote: str = Field(min_length=1)
    occurrence: int = Field(default=0, ge=0)
    act: AlignmentAct

    @field_validator("semantic_id", "quote")
    @classmethod
    def _text_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("semantic_id and quote must not be blank")
        return value


class TerminologyConfirmation(_DeeplyImmutableModel):
    """A terminology-agreement event with deterministic proposal provenance.

    ``proposal_turn`` addresses an assistant/public interviewer message in the
    public message ledger.  ``proposal_quote`` and ``proposal_occurrence``
    prove that the interviewer actually uttered the proposed term; ``quote``
    and ``occurrence`` independently anchor the stakeholder's agreement in the
    realized stakeholder message.
    """

    semantic_id: str = Field(min_length=1)
    proposed_term: str = Field(min_length=1)
    proposal_turn: int = Field(ge=0)
    proposal_quote: str = Field(min_length=1)
    proposal_occurrence: int = Field(default=0, ge=0)
    quote: str = Field(min_length=1)
    occurrence: int = Field(default=0, ge=0)

    @field_validator("semantic_id", "proposed_term", "proposal_quote", "quote")
    @classmethod
    def _text_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError(
                "semantic_id, proposed_term, proposal_quote, and quote "
                "must not be blank"
            )
        return value


class StakeholderResponse(_DeeplyImmutableModel):
    """Public message plus its private, deterministic semantic sidecar."""

    message: str = Field(min_length=1)
    annotations: tuple[SemanticAnnotation, ...] = Field(default_factory=tuple)
    alignments: tuple[ConceptAlignmentAssertion, ...] = Field(default_factory=tuple)
    terminology: tuple[TerminologyConfirmation, ...] = Field(default_factory=tuple)

    @field_validator("message")
    @classmethod
    def _message_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message must not be blank")
        return value


def semantic_mode_for_resolution(
    resolved: ResolvedSemanticAddress,
) -> SemanticMode:
    """Derive the one canonical mode for a successful address resolution."""
    if resolved.kind in ("node", "edge"):
        return "exists"
    if resolved.kind == "concept":
        return "mention"
    if resolved.kind == "node_element":
        return "value"
    if resolved.value is None:
        return "absent"
    if is_dont_know(resolved.value):
        return "dont_know"
    if resolved.kind in ("node_slot", "edge_slot"):
        return "value"
    raise ResponseValidationError(
        f"unsupported resolved semantic kind: {resolved.kind!r}",
        code="realization_semantic_mismatch",
    )


def canonical_semantic_mode(
    knowledge: StakeholderKnowledge | StakeholderKnowledgeGraph,
    semantic_id: str,
) -> SemanticMode:
    """Resolve a local ID and derive its canonical knowledge-backed mode."""
    return semantic_mode_for_resolution(
        resolve_semantic_address(knowledge, semantic_id)
    )


def _resolve_for_validation(
    knowledge: StakeholderKnowledge | StakeholderKnowledgeGraph,
    semantic_id: str,
    *,
    subject: str,
) -> ResolvedSemanticAddress:
    try:
        return resolve_semantic_address(knowledge, semantic_id)
    except SemanticAddressError as exc:
        raise ResponseValidationError(
            f"{subject} semantic_id {semantic_id!r} is not resolvable in "
            "stakeholder knowledge",
            code="unresolvable_semantic_address",
        ) from exc


def validate_response_plan(
    knowledge: StakeholderKnowledge | StakeholderKnowledgeGraph,
    plan: SemanticResponsePlan,
) -> SemanticResponsePlan:
    """Validate every planned item against the local canonical resolver."""
    for index, item in enumerate(plan.items):
        resolved = _resolve_for_validation(
            knowledge,
            item.semantic_id,
            subject=f"plan item {index}",
        )
        expected = semantic_mode_for_resolution(resolved)
        if item.mode != expected:
            raise ResponseValidationError(
                f"plan item {index} {item.semantic_id!r} declares mode "
                f"{item.mode!r}, but stakeholder knowledge requires {expected!r}",
                code="canonical_mode_mismatch",
            )
    return plan


def _occurrence_start(message: str, quote: str, occurrence: int) -> int | None:
    if occurrence < 0 or not quote:
        return None
    start = -1
    for _ in range(occurrence + 1):
        start = message.find(quote, start + 1)
        if start < 0:
            return None
    return start


def _require_message_span(
    message: str,
    quote: str,
    occurrence: int,
    *,
    subject: str,
) -> None:
    if _occurrence_start(message, quote, occurrence) is None:
        raise ResponseValidationError(
            f"{subject} quote {quote!r} occurrence {occurrence} is not an "
            "exact span of the response message"
        )


def _public_message_parts(
    message: object,
    fallback_turn: int,
) -> tuple[int, str, str] | None:
    """Read role/turn/text without depending on runtime or Inspect types."""
    if isinstance(message, Mapping):
        role = message.get("role")
        text = message.get("content", message.get("text"))
        turn = message.get("turn", message.get("public_message_turn", fallback_turn))
    elif (
        isinstance(message, tuple)
        and len(message) == 2
        and isinstance(message[0], str)
        and isinstance(message[1], str)
    ):
        role, text, turn = message[0], message[1], fallback_turn
    else:
        role = getattr(message, "role", None)
        text = getattr(message, "text", None)
        if not isinstance(text, str):
            text = getattr(message, "content", None)
        turn = getattr(message, "turn", fallback_turn)
        if not isinstance(turn, int):
            turn = getattr(message, "public_message_turn", fallback_turn)
    if not isinstance(role, str) or not isinstance(text, str) or not text:
        return None
    if not isinstance(turn, int) or isinstance(turn, bool) or turn < 0:
        return None
    return turn, role, text


def validate_terminology_provenance(
    terminology: Sequence[TerminologyConfirmation],
    interviewer_messages: Sequence[object] | None,
    *,
    response_public_message_turn: int | None = None,
) -> None:
    """Validate proposal and agreement spans without judging dialogue intent."""
    if not terminology:
        return
    if interviewer_messages is None:
        raise ResponseValidationError(
            "terminology provenance requires interviewer message history"
        )

    messages_by_turn: dict[int, tuple[str, str]] = {}
    for index, message in enumerate(interviewer_messages):
        parts = _public_message_parts(message, index)
        if parts is not None:
            turn, role, text = parts
            messages_by_turn[turn] = (role, text)

    for index, event in enumerate(terminology):
        proposal = messages_by_turn.get(event.proposal_turn)
        if proposal is None:
            raise ResponseValidationError(
                f"terminology {index} proposal_turn {event.proposal_turn!r} "
                "does not identify a public interviewer message"
            )
        role, text = proposal
        if role != "assistant":
            raise ResponseValidationError(
                f"terminology {index} proposal_turn {event.proposal_turn!r} "
                "must identify an assistant interviewer message"
            )
        if (
            response_public_message_turn is not None
            and event.proposal_turn >= response_public_message_turn
        ):
            raise ResponseValidationError(
                f"terminology {index} proposal_turn {event.proposal_turn!r} "
                "must precede the stakeholder response"
            )
        _require_message_span(
            text,
            event.proposal_quote,
            event.proposal_occurrence,
            subject=f"terminology {index} proposal",
        )
        if event.proposed_term not in event.proposal_quote:
            raise ResponseValidationError(
                f"terminology {index} proposed_term {event.proposed_term!r} "
                "is not an exact span of proposal_quote"
            )


def _private_identifiers(
    knowledge: StakeholderKnowledge | StakeholderKnowledgeGraph,
) -> set[str]:
    """Return only local handles that can appear in stakeholder instructions.

    Truth IDs are private projection metadata and are never rendered in the
    stakeholder prompt.  Treating them as public-message leakage tokens would
    reject ordinary language such as ``"Please send it to me."`` when a Truth
    node happens to be named ``"me"``.  The local graph namespace, including
    its full semantic addresses, is the only identifier surface that the
    response validator must guard.
    """
    graph = (
        knowledge.graph if isinstance(knowledge, StakeholderKnowledge) else knowledge
    )
    identifiers = set(graph.semantic_ids())
    identifiers.update(graph.nodes)
    identifiers.update(graph.edges)
    identifiers.update(graph.concepts)
    return {identifier for identifier in identifiers if identifier}


def _contains_identifier(message: str, identifier: str) -> bool:
    start = 0
    while True:
        index = message.find(identifier, start)
        if index < 0:
            return False
        before = message[index - 1] if index else ""
        after_index = index + len(identifier)
        after = message[after_index] if after_index < len(message) else ""
        if not (before.isalnum() or before == "_") and not (
            after.isalnum() or after == "_"
        ):
            return True
        start = index + 1


def _reject_private_identifier_leak(
    knowledge: StakeholderKnowledge | StakeholderKnowledgeGraph,
    message: str,
) -> None:
    for identifier in sorted(_private_identifiers(knowledge), key=len, reverse=True):
        if _contains_identifier(message, identifier):
            raise ResponseValidationError(
                f"public response message contains private identifier {identifier!r}"
            )


def _validate_concept_event(
    knowledge: StakeholderKnowledge | StakeholderKnowledgeGraph,
    semantic_id: str,
    quote: str,
    occurrence: int,
    message: str,
    *,
    subject: str,
) -> None:
    resolved = _resolve_for_validation(knowledge, semantic_id, subject=subject)
    if resolved.kind != "concept":
        raise ResponseValidationError(
            f"{subject} semantic_id {semantic_id!r} must resolve to a knowledge concept",
            code="realization_semantic_mismatch",
        )
    _require_message_span(
        message,
        quote,
        occurrence,
        subject=subject,
    )


def validate_stakeholder_response(
    knowledge: StakeholderKnowledge | StakeholderKnowledgeGraph,
    plan: SemanticResponsePlan,
    response: StakeholderResponse,
    *,
    interviewer_messages: Sequence[object] | None = None,
    response_public_message_turn: int | None = None,
) -> StakeholderResponse:
    """Validate a realized sidecar without inferring facts from prose."""
    validate_response_plan(knowledge, plan)
    _reject_private_identifier_leak(knowledge, response.message)

    plan_keys = {(item.semantic_id, item.mode) for item in plan.items}
    covered_keys: set[tuple[str, SemanticMode]] = set()
    for index, annotation in enumerate(response.annotations):
        resolved = _resolve_for_validation(
            knowledge,
            annotation.semantic_id,
            subject=f"annotation {index}",
        )
        expected = semantic_mode_for_resolution(resolved)
        if annotation.mode != expected:
            raise ResponseValidationError(
                f"annotation {index} {annotation.semantic_id!r} declares mode "
                f"{annotation.mode!r}, but stakeholder knowledge requires {expected!r}",
                code="canonical_mode_mismatch",
            )
        key = (annotation.semantic_id, annotation.mode)
        if key not in plan_keys:
            raise ResponseValidationError(
                f"annotation {index} asserts unplanned semantic item {key!r}"
            )
        _require_message_span(
            response.message,
            annotation.quote,
            annotation.occurrence,
            subject=f"annotation {index}",
        )
        covered_keys.add(key)

    missing = plan_keys - covered_keys
    if missing:
        raise ResponseValidationError(
            f"realized response is missing planned semantic items: {sorted(missing)!r}"
        )

    for index, event in enumerate(response.alignments):
        _validate_concept_event(
            knowledge,
            event.semantic_id,
            event.quote,
            event.occurrence,
            response.message,
            subject=f"alignment {index}",
        )

    for index, event in enumerate(response.terminology):
        _validate_concept_event(
            knowledge,
            event.semantic_id,
            event.quote,
            event.occurrence,
            response.message,
            subject=f"terminology {index}",
        )

    validate_terminology_provenance(
        response.terminology,
        interviewer_messages,
        response_public_message_turn=response_public_message_turn,
    )
    return response


def parse_semantic_response_plan(content: str) -> SemanticResponsePlan:
    """Parse only strict JSON into a response plan; do not repair model output."""
    try:
        return SemanticResponsePlan.model_validate_json(content)
    except (TypeError, ValueError) as exc:
        raise ResponseParseError("invalid SemanticResponsePlan JSON") from exc


def parse_stakeholder_response(content: str) -> StakeholderResponse:
    """Parse only strict JSON into a stakeholder response sidecar."""
    try:
        return StakeholderResponse.model_validate_json(content)
    except (TypeError, ValueError) as exc:
        raise ResponseParseError("invalid StakeholderResponse JSON") from exc


__all__ = [
    "AlignmentAct",
    "ConceptAlignmentAssertion",
    "PlannedResponseItem",
    "ResponseParseError",
    "ResponseValidationCode",
    "ResponseValidationError",
    "SemanticAnnotation",
    "SemanticMode",
    "SemanticResponsePlan",
    "StakeholderResponse",
    "TerminologyConfirmation",
    "canonical_semantic_mode",
    "parse_semantic_response_plan",
    "parse_stakeholder_response",
    "semantic_mode_for_resolution",
    "validate_response_plan",
    "validate_stakeholder_response",
    "validate_terminology_provenance",
]
