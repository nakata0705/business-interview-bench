"""Standalone stakeholder identity, visibility, and forgetting configuration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

NodeProperty = Literal["activity", "actor", "system", "reads", "writes", "rationale"]
EdgeProperty = Literal["condition"]


def _nonempty(value: str, field_name: str) -> str:
    if not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    return value


def _sorted_string_values(value: object) -> object:
    if isinstance(value, (list, tuple, set, frozenset)) and all(
        isinstance(item, str) for item in value
    ):
        return tuple(sorted(set(value)))
    return value


def _normalize_override_input(value: object) -> object:
    if not isinstance(value, Mapping):
        return value
    payload = dict(value)
    if "local_terms" in payload:
        payload["local_terms"] = _sorted_string_values(payload["local_terms"])
    return payload


def _normalize_profile_input(value: object) -> object:
    if not isinstance(value, Mapping):
        return value
    payload = dict(value)
    for field_name in ("visible_node_ids", "visible_edge_ids"):
        if field_name in payload:
            payload[field_name] = _sorted_string_values(payload[field_name])

    for field_name in ("visible_node_attributes", "visible_edge_attributes"):
        raw = payload.get(field_name)
        if not isinstance(raw, Mapping):
            continue
        normalized: dict[object, object] = {}
        for key, properties in raw.items():
            normalized[key] = _sorted_string_values(properties)
        payload[field_name] = {
            key: normalized[key] for key in sorted(normalized, key=str)
        }

    overrides = payload.get("concept_overrides")
    if isinstance(overrides, Mapping):
        normalized_overrides = {
            key: _normalize_override_input(item) for key, item in overrides.items()
        }
        payload["concept_overrides"] = {
            key: normalized_overrides[key]
            for key in sorted(normalized_overrides, key=str)
        }
    return payload


class ConceptKnowledgeOverride(BaseModel):
    """Per-Truth-concept knobs for a future knowledge projection.

    Description and terminology knowledge are independent. ``local_terms``
    may intentionally contain stakeholder wording that differs from Truth;
    this model does not resolve or project it.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    description_known: bool = True
    terms_known: bool = Field(
        default=True,
        validation_alias=AliasChoices("terms_known", "terminology_known"),
    )
    local_terms: tuple[str, ...] | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalize_input(cls, value: object) -> object:
        return _normalize_override_input(value)

    @field_validator("local_terms")
    @classmethod
    def _terms_are_nonempty(
        cls, value: tuple[str, ...] | None
    ) -> tuple[str, ...] | None:
        if value is not None and any(not term.strip() for term in value):
            raise ValueError("local_terms entries must not be empty")
        return value

    @property
    def terminology_known(self) -> bool:
        """Alias for callers that use the longer semantic name."""
        return self.terms_known


class ForgettingConfig(BaseModel):
    """Bounded forgetting policy configuration, without sampling behavior."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    baseline_forget_probability: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        validation_alias=AliasChoices(
            "baseline_forget_probability", "forget_probability"
        ),
    )
    node_forget_probability: float = Field(default=0.0, ge=0.0, le=1.0)
    edge_forget_probability: float = Field(default=0.0, ge=0.0, le=1.0)
    property_forget_probability: float = Field(default=0.0, ge=0.0, le=1.0)
    max_retries: int = Field(default=32, ge=1)
    allow_shortcut_contraction: bool = True

    @property
    def forget_probability(self) -> float:
        """Source-compatible alias for the baseline probability."""
        return self.baseline_forget_probability

    @property
    def safe_shortcut_contraction(self) -> bool:
        """Alias for whether safe shortcut contraction is permitted."""
        return self.allow_shortcut_contraction

    @property
    def effective_node_probability(self) -> float:
        return max(self.baseline_forget_probability, self.node_forget_probability)

    @property
    def effective_edge_probability(self) -> float:
        return max(self.baseline_forget_probability, self.edge_forget_probability)


# Descriptive and source-shaped names are aliases, not separate hierarchies.
StakeholderForgettingConfig = ForgettingConfig


class StakeholderProfile(BaseModel):
    """Stable stakeholder identity and Truth visibility configuration.

    The IDs in this configuration address canonical Truth elements. They are
    projection inputs, not the opaque local IDs used by ``StakeholderKnowledge``.
    A future stochastic projection may consume this value object; Phase 9 only
    defines and serializes it.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    stakeholder_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    role: str | None = None
    visible_node_ids: tuple[str, ...] = Field(default_factory=tuple)
    visible_edge_ids: tuple[str, ...] = Field(default_factory=tuple)
    visible_node_attributes: dict[str, tuple[NodeProperty, ...]] = Field(
        default_factory=dict
    )
    visible_edge_attributes: dict[str, tuple[EdgeProperty, ...]] = Field(
        default_factory=dict
    )
    concept_overrides: dict[str, ConceptKnowledgeOverride] = Field(default_factory=dict)
    forgetting: ForgettingConfig = Field(default_factory=ForgettingConfig)

    @model_validator(mode="before")
    @classmethod
    def _normalize_input(cls, value: object) -> object:
        return _normalize_profile_input(value)

    @field_validator("stakeholder_id", "name")
    @classmethod
    def _identity_is_nonempty(cls, value: str, info) -> str:
        return _nonempty(value, info.field_name)

    @field_validator("role")
    @classmethod
    def _role_is_nonempty(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("role must not be empty when supplied")
        return value

    @field_validator("visible_node_ids", "visible_edge_ids")
    @classmethod
    def _visible_ids_are_nonempty(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item.strip() for item in value):
            raise ValueError("visible IDs must not be empty")
        return value

    @field_validator("visible_node_attributes", "visible_edge_attributes")
    @classmethod
    def _attribute_keys_are_nonempty(
        cls, value: dict[str, tuple[str, ...]]
    ) -> dict[str, tuple[str, ...]]:
        if any(not key.strip() for key in value):
            raise ValueError("visibility mapping IDs must not be empty")
        return value

    def node_properties_for(self, node_id: str) -> set[NodeProperty]:
        """Return the configured known properties for one Truth node."""
        return set(self.visible_node_attributes.get(node_id, ()))

    def edge_properties_for(self, edge_id: str) -> set[EdgeProperty]:
        """Return the configured known properties for one Truth edge."""
        return set(self.visible_edge_attributes.get(edge_id, ()))

    def concept_override_for(self, concept_id: str) -> ConceptKnowledgeOverride | None:
        """Return one optional per-concept override without applying it."""
        return self.concept_overrides.get(concept_id)


# The source calls this concern a filter; the standalone public model is a
# profile because it also carries stable identity and generation policy.
StakeholderFilter = StakeholderProfile


__all__ = [
    "ConceptKnowledgeOverride",
    "EdgeProperty",
    "ForgettingConfig",
    "NodeProperty",
    "StakeholderFilter",
    "StakeholderForgettingConfig",
    "StakeholderProfile",
]
