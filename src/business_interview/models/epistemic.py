"""Explicit Agent epistemic states.

Truth slots use ``ConceptRef | None``. Agent slots use the four-state union
below, so an uninvestigated slot cannot be confused with an explicit absence
or an explicit inability to know.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .concepts import ConceptRef, EvidenceRef


class UnsetType(BaseModel):
    """The Agent has not reached a conclusion for this slot."""

    state: Literal["unset"] = "unset"

    @property
    def asserted(self) -> bool:
        return False


UNSET = UnsetType()


class AbsentType(BaseModel):
    """The Agent explicitly established that a value is absent."""

    state: Literal["absent"] = "absent"
    evidence: list[EvidenceRef] = Field(default_factory=list)

    @property
    def asserted(self) -> bool:
        return True


ABSENT = AbsentType()


class DontKnowType(BaseModel):
    """The Agent explicitly established that a value is unknowable."""

    state: Literal["dont_know"] = "dont_know"
    evidence: list[EvidenceRef] = Field(default_factory=list)

    @property
    def asserted(self) -> bool:
        return True


DONT_KNOW = DontKnowType()

AgentSlot = ConceptRef | UnsetType | AbsentType | DontKnowType
AgentListSlot = list[ConceptRef] | UnsetType | AbsentType | DontKnowType
TruthSlot = ConceptRef | None
TruthListSlot = list[ConceptRef] | None


def is_unset(value: object) -> bool:
    """Return whether ``value`` is the explicit UNSET state."""
    return isinstance(value, UnsetType)


def is_absent(value: object) -> bool:
    """Return whether ``value`` is the explicit ABSENT state."""
    return isinstance(value, AbsentType)


def is_dont_know(value: object) -> bool:
    """Return whether ``value`` is the explicit DONT_KNOW state."""
    return isinstance(value, DontKnowType)
