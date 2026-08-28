"""Deterministic catalog for the standalone business-interview scenarios."""

from __future__ import annotations

import json
from collections.abc import Sequence
from importlib.resources import files
from pathlib import PurePosixPath
from typing import Any

from pydantic import BaseModel, ConfigDict

from business_interview.models import BusinessProcessGraph

from .models import (
    InitialMessage,
    ScenarioDefinition,
    ScenarioLocale,
    StakeholderPrompt,
)

_CATALOG_RESOURCE = "data/catalog.json"


class UnknownScenarioError(LookupError):
    """Raised when a caller requests an ID outside the explicit catalog."""

    def __init__(self, scenario_id: object, supported_ids: Sequence[str]) -> None:
        supported = ", ".join(repr(item) for item in supported_ids)
        super().__init__(
            f"unknown scenario ID {scenario_id!r}; supported IDs: {supported}"
        )
        self.scenario_id = scenario_id
        self.supported_ids = tuple(supported_ids)


class _CatalogRecord(BaseModel):
    """Serialized catalog metadata before its Truth resource is loaded."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    canonical_scenario_id: str
    locale: ScenarioLocale
    truth_resource: str
    prompt: StakeholderPrompt
    initial_messages: tuple[InitialMessage, ...]


def _read_json(resource_name: str) -> Any:
    path = PurePosixPath(resource_name)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"invalid scenario resource path: {resource_name!r}")
    resource = files("business_interview.scenarios").joinpath(*path.parts)
    try:
        text = resource.read_text(encoding="utf-8")
        return json.loads(text)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"could not read scenario resource: {resource_name!r}"
        ) from exc


def _catalog_records() -> tuple[_CatalogRecord, ...]:
    payload = _read_json(_CATALOG_RESOURCE)
    if not isinstance(payload, list):
        raise ValueError("scenario catalog must contain a JSON array")
    records = tuple(_CatalogRecord.model_validate(item) for item in payload)
    ids = [record.id for record in records]
    if len(ids) != len(set(ids)):
        raise ValueError("scenario catalog contains duplicate IDs")
    return records


def _definition(record: _CatalogRecord) -> ScenarioDefinition:
    truth = BusinessProcessGraph.model_validate(
        _read_json(f"data/{record.truth_resource}")
    )
    return ScenarioDefinition(
        id=record.id,
        canonical_scenario_id=record.canonical_scenario_id,
        locale=record.locale,
        truth=truth,
        prompt=record.prompt,
        initial_messages=record.initial_messages,
    )


def list_scenarios() -> list[ScenarioDefinition]:
    """Return fresh scenario definitions in deterministic catalog order."""
    return [_definition(record) for record in _catalog_records()]


def get_scenario(scenario_id: str) -> ScenarioDefinition:
    """Load one explicit catalog ID, rejecting unknown IDs.

    No suffix-based locale transformation is performed.  Each supported ID is
    a concrete catalog record, while localized records may share a Truth
    resource through their ``canonical_scenario_id``.
    """
    records = _catalog_records()
    for record in records:
        if record.id == scenario_id:
            return _definition(record)
    raise UnknownScenarioError(scenario_id, [record.id for record in records])


__all__ = ["UnknownScenarioError", "get_scenario", "list_scenarios"]
