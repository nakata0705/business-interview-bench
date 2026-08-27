"""Concept references and diagnostic observation evidence."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

ConceptKind = Literal["activity", "actor", "system", "data", "condition", "rationale"]


class EvidenceRef(BaseModel):
    """Optional diagnostic citation of an observation span.

    Evidence does not participate in graph validity. It is deliberately a
    small value object so later evaluation code can inspect it without adding
    a conversation or tau2 dependency to the domain model.
    """

    observation_id: str
    quote: str | None = None
    occurrence: int = Field(default=0, ge=0)

    def resolve_span(self, text: str) -> tuple[int, int] | None:
        """Return the selected quote span, or ``None`` when it is not found."""
        if not self.quote:
            return None
        start = -1
        for _ in range(self.occurrence + 1):
            start = text.find(self.quote, start + 1)
            if start < 0:
                return None
        return start, start + len(self.quote)


class ConceptRef(BaseModel):
    """A value-bearing reference to a concept in a graph-local namespace."""

    state: Literal["value"] = "value"
    concept_id: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    evidence: list[EvidenceRef] = Field(default_factory=list)

    @field_validator("concept_id")
    @classmethod
    def _concept_id_not_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("concept_id must not be empty")
        return value

    @property
    def asserted(self) -> bool:
        """Whether this reference is an active claim."""
        return self.confidence > 0.0
