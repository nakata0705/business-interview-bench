"""Phase 15 provider-compatibility checks for candidate Inspect tools."""

# The workspace-level resolver may not see Inspect's dev group.
# Project-level ``uv run pyright`` is authoritative for these tests.
# pyright: reportMissingImports=false

from __future__ import annotations

import json
from typing import Any

from inspect_ai.tool._tool_def import tool_registry_info
from inspect_ai.tool._tool_info import parse_tool_info

from business_interview.runtime import create_live_interview_store
from business_interview_bench.inspect_adapter.tools import build_interview_tools

_EXPECTED_TOOL_NAMES = {
    "get_agent_graph",
    "get_observations",
    "add_node",
    "remove_node",
    "add_edge",
    "remove_edge",
    "define_concept",
    "remove_concept",
    "set_node_property",
    "set_node_property_list",
    "set_node_absent",
    "set_node_dont_know",
    "set_edge_condition",
    "set_edge_condition_absent",
    "set_edge_condition_dont_know",
    "attach_evidence",
    "set_start_nodes",
    "set_end_nodes",
    "complete_interview",
}


def _schemas() -> dict[str, dict[str, Any]]:
    runtime = create_live_interview_store("phase15-schema-test")
    schemas: dict[str, dict[str, Any]] = {}
    for candidate_tool in build_interview_tools([runtime]):
        name = tool_registry_info(candidate_tool)[0]
        info = parse_tool_info(candidate_tool)
        schemas[name] = info.parameters.model_dump(exclude_none=True)
    return schemas


def _assert_provider_schema(schema: Any, path: str = "$") -> None:
    """Reject schemas that OpenAI-compatible providers treat as free-form."""
    assert isinstance(schema, dict) and schema, f"empty schema at {path}"

    if "anyOf" in schema or "oneOf" in schema:
        variants = schema.get("anyOf", schema.get("oneOf"))
        assert isinstance(variants, list) and variants, f"invalid union at {path}"
        for index, variant in enumerate(variants):
            _assert_provider_schema(variant, f"{path}[{index}]")
        return

    schema_type = schema.get("type")
    assert schema_type in {
        "array",
        "boolean",
        "integer",
        "null",
        "number",
        "object",
        "string",
    }, f"missing or invalid type at {path}: {schema}"

    if schema_type == "object":
        assert schema.get("additionalProperties") is False, (
            f"object must reject free-form properties at {path}"
        )
        properties = schema.get("properties")
        assert isinstance(properties, dict), f"missing properties at {path}"
        required = schema.get("required", [])
        assert isinstance(required, list), f"invalid required at {path}"
        assert set(required) <= set(properties), f"unknown required field at {path}"
        for name, child in properties.items():
            _assert_provider_schema(child, f"{path}.properties[{name!r}]")
    elif schema_type == "array":
        assert "items" in schema, f"array must declare items at {path}"
        _assert_provider_schema(schema["items"], f"{path}.items")

    assert "additionalProperties" not in schema or schema_type == "object"
    assert "patternProperties" not in schema
    assert "unevaluatedProperties" not in schema


def test_candidate_tool_surface_is_typed_for_openai_compatible_schemas() -> None:
    schemas = _schemas()

    assert set(schemas) == _EXPECTED_TOOL_NAMES
    assert len(schemas) == 19
    for name, schema in schemas.items():
        _assert_provider_schema(schema, f"{name}.parameters")
        json.dumps(schema, ensure_ascii=False, sort_keys=True)

    scalar = schemas["set_node_property"]["properties"]
    assert scalar["value"]["type"] == "string"
    assert scalar["property_name"]["enum"] == [
        "activity",
        "actor",
        "system",
        "rationale",
    ]

    list_value = schemas["set_node_property_list"]["properties"]
    assert list_value["concept_ids"] == {
        "type": "array",
        "description": "Existing candidate concept IDs.",
        "items": {"type": "string"},
    }
    assert "evidence" not in schemas["set_node_absent"]["properties"]
    assert "evidence" not in schemas["set_node_dont_know"]["properties"]
    assert "evidence" not in schemas["set_edge_condition_absent"]["properties"]
    assert "evidence" not in schemas["set_edge_condition_dont_know"]["properties"]


def test_candidate_tool_surface_has_no_generic_update_operations() -> None:
    schemas = _schemas()
    assert not {name for name in schemas if name.startswith("update_")}
    assert "updates" not in json.dumps(schemas, ensure_ascii=False, sort_keys=True)
