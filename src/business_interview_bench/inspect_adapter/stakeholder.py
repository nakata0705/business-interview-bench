"""Thin Inspect adapter for one two-call stakeholder response."""

# The workspace-level auxiliary resolver may not see the Inspect dev group.
# Project-level ``uv run pyright`` remains the authoritative adapter check.
# pyright: reportMissingImports=false

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass

from inspect_ai.model import (
    ChatMessage,
    ChatMessageSystem,
    ChatMessageUser,
    Model,
    get_model,
)

from business_interview.runtime import SemanticLedger
from business_interview.scenarios import StakeholderPrompt
from business_interview.stakeholders.knowledge import (
    StakeholderKnowledge,
    validate_stakeholder_knowledge,
)
from business_interview.stakeholders.prompting import render_knowledge_prompt
from business_interview.stakeholders.response import (
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
    "Use local IDs exactly as shown."
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
    "with an exact message span, add no unplanned business assertion, and "
    "never put local IDs in message. Include terminology only when the "
    "assistant history contains the exact proposed term and preserve both "
    "proposal and agreement provenance fields."
)


class StakeholderResponseError(ValueError):
    """Raised when bounded semantic retry cannot produce a valid response."""


@dataclass(frozen=True, slots=True)
class StakeholderTurn:
    """The validated private WHAT/HOW pair for one public response."""

    plan: SemanticResponsePlan
    response: StakeholderResponse


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


def _retry_instruction(instruction: str, error: ValueError | None) -> str:
    if error is None:
        return instruction
    reason = " ".join(str(error).split())[:240]
    return f"{instruction}\nPrevious output rejected: {reason} Return corrected JSON."


def _attempts_are_positive(plan_attempts: int, realization_attempts: int) -> None:
    if plan_attempts < 1 or realization_attempts < 1:
        raise ValueError("retry attempt limits must be positive")


async def _generate_plan(
    model: Model,
    conversation: Sequence[ChatMessage],
    knowledge: StakeholderKnowledge,
    system_context: str,
    max_attempts: int,
) -> SemanticResponsePlan:
    error: ValueError | None = None
    for _attempt in range(max_attempts):
        output = await model.generate(
            _model_input(
                conversation,
                system_context,
                _retry_instruction(_PLAN_INSTRUCTION, error),
            )
        )
        try:
            plan = parse_semantic_response_plan(output.completion)
            return validate_response_plan(knowledge, plan)
        except ValueError as exc:
            error = exc
    if error is None:
        raise StakeholderResponseError("stakeholder response plan had no attempts")
    raise StakeholderResponseError(
        f"stakeholder response plan rejected after {max_attempts} attempts: {error}"
    ) from error


async def _realize_response(
    model: Model,
    conversation: Sequence[ChatMessage],
    knowledge: StakeholderKnowledge,
    system_context: str,
    plan: SemanticResponsePlan,
    max_attempts: int,
) -> StakeholderResponse:
    plan_json = json.dumps(plan.model_dump(mode="json"), ensure_ascii=False)
    instruction = f"{_REALIZATION_INSTRUCTION}\nValidated private plan: {plan_json}"
    error: ValueError | None = None
    for _attempt in range(max_attempts):
        output = await model.generate(
            _model_input(
                conversation,
                system_context,
                _retry_instruction(instruction, error),
            )
        )
        try:
            response = parse_stakeholder_response(output.completion)
            return validate_stakeholder_response(
                knowledge,
                plan,
                response,
                interviewer_messages=conversation,
                response_public_message_turn=len(conversation),
            )
        except ValueError as exc:
            error = exc
    if error is None:
        raise StakeholderResponseError("stakeholder response had no attempts")
    raise StakeholderResponseError(
        f"stakeholder response rejected after {max_attempts} attempts: {error}"
    ) from error


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
    plan = await _generate_plan(
        model,
        conversation,
        knowledge,
        system_context,
        max_plan_attempts,
    )
    response = await _realize_response(
        model,
        conversation,
        knowledge,
        system_context,
        plan,
        max_realization_attempts,
    )
    return StakeholderTurn(plan=plan, response=response)


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
    "StakeholderResponseError",
    "StakeholderTurn",
    "invoke_stakeholder_response",
    "invoke_stakeholder_response_with_plan",
]
