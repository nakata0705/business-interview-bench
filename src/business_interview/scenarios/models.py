"""Tau2-free scenario identity, Truth, and public prompt models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from business_interview.models import BusinessProcessGraph, validate_canonical_graph

ScenarioLocale = Literal["en", "ja"]


class StakeholderPrompt(BaseModel):
    """Public task instructions, separate from Truth and private knowledge."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    persona: str
    reason_for_call: str
    task_instructions: str


class InitialMessage(BaseModel):
    """One ordered role/content message from a scenario's initial history."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    role: str
    content: str


class ScenarioDefinition(BaseModel):
    """A runnable scenario's public input contract.

    The definition deliberately contains canonical Truth and public prompt
    metadata only.  Stakeholder simulator state and private knowledge are
    constructed separately by a future runtime.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    canonical_scenario_id: str = Field(min_length=1)
    locale: ScenarioLocale
    truth: BusinessProcessGraph
    prompt: StakeholderPrompt
    initial_messages: tuple[InitialMessage, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _validate_truth(self) -> ScenarioDefinition:
        validate_canonical_graph(self.truth)
        return self


__all__ = [
    "InitialMessage",
    "ScenarioDefinition",
    "ScenarioLocale",
    "StakeholderPrompt",
]
