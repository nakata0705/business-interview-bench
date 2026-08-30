"""Thin Inspect adapter for one two-call stakeholder response."""

# The workspace-level auxiliary resolver may not see the Inspect dev group.
# Project-level ``uv run pyright`` remains the authoritative adapter check.
# pyright: reportMissingImports=false

from __future__ import annotations

import json
from collections.abc import Sequence

from inspect_ai.model import (
    ChatMessage,
    ChatMessageSystem,
    ChatMessageUser,
    Model,
    get_model,
)

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
    '"alignments": [], "terminology": []}. '
    "Naturally express every item in the validated plan, annotate each item "
    "with an exact message span, add no unplanned business assertion, and "
    "never put local IDs in message."
)


class StakeholderResponseError(ValueError):
    """Raised when bounded semantic retry cannot produce a valid response."""


def _model_input(
    conversation: Sequence[ChatMessage],
    knowledge_prompt: str,
    instruction: str,
) -> list[ChatMessage]:
    return [
        ChatMessageSystem(content=knowledge_prompt),
        *conversation,
        ChatMessageUser(content=instruction),
    ]


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
    knowledge_prompt: str,
    max_attempts: int,
) -> SemanticResponsePlan:
    error: ValueError | None = None
    for _attempt in range(max_attempts):
        output = await model.generate(
            _model_input(
                conversation,
                knowledge_prompt,
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
    knowledge_prompt: str,
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
                knowledge_prompt,
                _retry_instruction(instruction, error),
            )
        )
        try:
            response = parse_stakeholder_response(output.completion)
            return validate_stakeholder_response(knowledge, plan, response)
        except ValueError as exc:
            error = exc
    if error is None:
        raise StakeholderResponseError("stakeholder response had no attempts")
    raise StakeholderResponseError(
        f"stakeholder response rejected after {max_attempts} attempts: {error}"
    ) from error


async def invoke_stakeholder_response(
    conversation: Sequence[ChatMessage],
    knowledge: StakeholderKnowledge,
    *,
    max_plan_attempts: int = _DEFAULT_MAX_ATTEMPTS,
    max_realization_attempts: int = _DEFAULT_MAX_ATTEMPTS,
) -> StakeholderResponse:
    """Generate one validated stakeholder response using exactly two phases.

    The stakeholder role is required explicitly; the current candidate model
    is never used as an implicit fallback. Provider errors are allowed to
    propagate separately from bounded semantic-output retries.
    """
    _attempts_are_positive(max_plan_attempts, max_realization_attempts)
    validate_stakeholder_knowledge(knowledge)
    model = get_model(role="stakeholder", required=True)
    knowledge_prompt = render_knowledge_prompt(knowledge)
    plan = await _generate_plan(
        model,
        conversation,
        knowledge,
        knowledge_prompt,
        max_plan_attempts,
    )
    return await _realize_response(
        model,
        conversation,
        knowledge,
        knowledge_prompt,
        plan,
        max_realization_attempts,
    )


__all__ = ["StakeholderResponseError", "invoke_stakeholder_response"]
