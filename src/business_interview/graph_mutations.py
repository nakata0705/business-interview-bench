"""Pure, validated mutations for an interviewer's :class:`AgentGraph`.

The interview adapter exposes these operations as tools, but all graph
semantics live here.  Every operation takes a graph and returns a new graph;
it never mutates the input graph.  Evidence references are attached to the
same graph-local objects used by the deterministic evaluator.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Literal

from pydantic import ValidationError

from business_interview.models import (
    UNSET,
    AbsentType,
    AgentConcept,
    AgentEdge,
    AgentGraph,
    AgentNode,
    ConceptRef,
    DontKnowType,
    EvidenceRef,
    UnsetType,
)

_NODE_PROPERTIES = (
    "activity",
    "actor",
    "system",
    "reads",
    "writes",
    "rationale",
)
_EDGE_PROPERTIES = ("condition",)
_EPISTEMIC_STATES = {"unset", "absent", "dont_know"}


class GraphMutationError(ValueError):
    """Raised when a requested graph mutation would be invalid."""


def _nonempty(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GraphMutationError(f"{label} must be a non-empty string")
    return value


def _graph(value: AgentGraph | Mapping[str, Any]) -> AgentGraph:
    try:
        graph = (
            value if isinstance(value, AgentGraph) else AgentGraph.model_validate(value)
        )
    except (TypeError, ValidationError) as exc:
        raise GraphMutationError("current AgentGraph is not valid") from exc
    errors = graph.structure_errors()
    errors.extend(
        f"node mapping key does not match node.id: {key!r}"
        for key, node in graph.nodes.items()
        if key != node.id
    )
    errors.extend(
        f"edge mapping key does not match edge.id: {key!r}"
        for key, edge in graph.edges.items()
        if key != edge.id
    )
    if len(graph.start_node_ids) != len(set(graph.start_node_ids)):
        errors.append("start_node_ids must be unique")
    if len(graph.end_node_ids) != len(set(graph.end_node_ids)):
        errors.append("end_node_ids must be unique")
    if errors:
        raise GraphMutationError(
            "current AgentGraph is invalid:\n- " + "\n- ".join(errors)
        )
    return graph


def _clone(value: AgentGraph | Mapping[str, Any]) -> AgentGraph:
    """Validate and deeply copy a graph before applying a mutation."""
    graph = _graph(value)
    try:
        return AgentGraph.model_validate(graph.model_dump(mode="python"))
    except ValidationError as exc:  # pragma: no cover - guarded by _graph
        raise GraphMutationError("could not copy AgentGraph") from exc


def _finish(graph: AgentGraph) -> AgentGraph:
    _graph(graph)
    return graph


def _evidence(value: EvidenceRef | Mapping[str, Any]) -> EvidenceRef:
    try:
        result = (
            value
            if isinstance(value, EvidenceRef)
            else EvidenceRef.model_validate(value)
        )
    except (TypeError, ValidationError) as exc:
        raise GraphMutationError("invalid EvidenceRef") from exc
    _nonempty(result.observation_id, "EvidenceRef.observation_id")
    return result.model_copy(deep=True)


def _evidence_list(
    values: Iterable[EvidenceRef | Mapping[str, Any]],
) -> list[EvidenceRef]:
    return [_evidence(value) for value in values]


def _marker(
    state: Literal["unset", "absent", "dont_know"],
    evidence: Iterable[EvidenceRef | Mapping[str, Any]] = (),
) -> Any:
    refs = _evidence_list(evidence)
    if state == "unset":
        if refs:
            raise GraphMutationError("UNSET cannot carry evidence")
        return UNSET.model_copy(deep=True)
    if state == "absent":
        return AbsentType(evidence=refs)
    return DontKnowType(evidence=refs)


def _concept_ref(value: str | ConceptRef | Mapping[str, Any]) -> ConceptRef:
    if isinstance(value, ConceptRef):
        return value.model_copy(deep=True)
    if isinstance(value, str):
        return ConceptRef(concept_id=_nonempty(value, "concept_id"))
    try:
        return ConceptRef.model_validate(value)
    except (TypeError, ValidationError) as exc:
        raise GraphMutationError("invalid ConceptRef") from exc


def _slot_value(value: Any, *, list_slot: bool = False) -> Any:
    """Coerce a public mutation value into an Agent slot value.

    Tool arguments deliberately use JSON-friendly strings and objects.  A
    string naming a concept is a value reference; ``ABSENT``, ``DONT_KNOW``,
    and ``UNSET`` are explicit epistemic markers.  Lists are accepted only for
    ``reads`` and ``writes``.
    """
    if isinstance(value, (ConceptRef, UnsetType, AbsentType, DontKnowType)):
        if isinstance(value, ConceptRef) and list_slot:
            return [value.model_copy(deep=True)]
        if not list_slot and isinstance(value, list):
            raise GraphMutationError("scalar slot cannot contain a list")
        return value.model_copy(deep=True)

    if value is None:
        raise GraphMutationError(
            "Agent slots do not accept null; use explicit state 'absent'"
        )

    if isinstance(value, str):
        state = value.strip().lower()
        if state in _EPISTEMIC_STATES:
            if list_slot and state == "unset":
                return _marker("unset")
            return _marker(state)  # type: ignore[arg-type]
        ref = _concept_ref(value)
        return [ref] if list_slot else ref

    if isinstance(value, Mapping):
        state = value.get("state")
        if state in _EPISTEMIC_STATES:
            if list_slot and state == "unset":
                return _marker("unset", value.get("evidence", ()))
            return _marker(state, value.get("evidence", ()))  # type: ignore[arg-type]
        ref = _concept_ref(value)
        return [ref] if list_slot else ref

    if (
        list_slot
        and isinstance(value, Sequence)
        and not isinstance(value, (str, bytes, bytearray))
    ):
        return [_concept_ref(item) for item in value]

    raise GraphMutationError("invalid Agent slot value")


def _property_name(value: str, allowed: Sequence[str]) -> str:
    name = _nonempty(value, "property_name")
    if name == "necessity_rationale":
        name = "rationale"
    if name not in allowed:
        raise GraphMutationError(
            f"unknown property {value!r}; expected one of {tuple(allowed)!r}"
        )
    return name


def _node_from_input(
    node: AgentNode | Mapping[str, Any] | None,
    *,
    node_id: str | None,
    fields: Mapping[str, Any],
) -> AgentNode:
    payload: dict[str, Any]
    if isinstance(node, AgentNode):
        payload = node.model_dump(mode="python")
    elif node is None:
        payload = {}
    else:
        payload = dict(node)
    if node_id is not None:
        payload["id"] = node_id
    if "rationale" in payload and "necessity_rationale" not in payload:
        payload["necessity_rationale"] = payload.pop("rationale")
    payload.update(fields)
    if "id" not in payload:
        raise GraphMutationError("node id is required")
    for property_name in _NODE_PROPERTIES:
        attribute = (
            "necessity_rationale" if property_name == "rationale" else property_name
        )
        if attribute in payload:
            payload[attribute] = _slot_value(
                payload[attribute],
                list_slot=property_name in ("reads", "writes"),
            )
    try:
        return AgentNode.model_validate(payload)
    except (TypeError, ValidationError) as exc:
        raise GraphMutationError("invalid AgentNode") from exc


def add_node(
    graph: AgentGraph | Mapping[str, Any],
    node: AgentNode | Mapping[str, Any] | str | None = None,
    *,
    node_id: str | None = None,
    **fields: Any,
) -> AgentGraph:
    """Return a graph with one new node, rejecting duplicate IDs."""
    if isinstance(node, str):
        if node_id is not None:
            raise GraphMutationError("node ID was supplied twice")
        node_id = node
        node = None
    value = _node_from_input(node, node_id=node_id, fields=fields)
    value.id = _nonempty(value.id, "node id")
    result = _clone(graph)
    if value.id in result.nodes:
        raise GraphMutationError(f"node already exists: {value.id!r}")
    result.nodes[value.id] = value
    return _finish(result)


def update_node(
    graph: AgentGraph | Mapping[str, Any],
    node_id: str,
    node: AgentNode | Mapping[str, Any] | None = None,
    *,
    updates: Mapping[str, Any] | None = None,
    **fields: Any,
) -> AgentGraph:
    """Return a graph with one existing node replaced or partially updated."""
    node_id = _nonempty(node_id, "node_id")
    result = _clone(graph)
    if node_id not in result.nodes:
        raise GraphMutationError(f"node does not exist: {node_id!r}")
    if node is not None:
        if isinstance(node, Mapping) and "id" not in node:
            patch = dict(node)
            patch.update(dict(updates or {}))
            patch.update(fields)
            if "rationale" in patch and "necessity_rationale" not in patch:
                patch["necessity_rationale"] = patch.pop("rationale")
            payload = result.nodes[node_id].model_dump(mode="python")
            payload.update(patch)
            updated_node = _node_from_input(
                payload,
                node_id=None,
                fields={},
            )
            if updated_node.id != node_id:
                raise GraphMutationError("node ID cannot be changed by update_node")
            result.nodes[node_id] = updated_node
            return _finish(result)
        replacement = _node_from_input(node, node_id=None, fields={})
        if replacement.id != node_id:
            raise GraphMutationError("replacement node id does not match node_id")
        if updates or fields:
            patch = dict(updates or {})
            patch.update(fields)
            if "rationale" in patch and "necessity_rationale" not in patch:
                patch["necessity_rationale"] = patch.pop("rationale")
            payload = replacement.model_dump(mode="python")
            payload.update(patch)
            replacement = _node_from_input(payload, node_id=None, fields={})
        result.nodes[node_id] = replacement
        return _finish(result)

    patch = dict(updates or {})
    patch.update(fields)
    if not patch:
        raise GraphMutationError("node update requires at least one field")
    if "rationale" in patch and "necessity_rationale" not in patch:
        patch["necessity_rationale"] = patch.pop("rationale")
    payload = result.nodes[node_id].model_dump(mode="python")
    payload.update(patch)
    try:
        updated_node = _node_from_input(
            payload,
            node_id=None,
            fields={},
        )
        if updated_node.id != node_id:
            raise GraphMutationError("node ID cannot be changed by update_node")
        result.nodes[node_id] = updated_node
    except (TypeError, ValidationError, GraphMutationError) as exc:
        raise GraphMutationError("invalid node update") from exc
    return _finish(result)


def remove_node(
    graph: AgentGraph | Mapping[str, Any],
    node_id: str,
) -> AgentGraph:
    """Return a graph without a node, rejecting dangling incident edges."""
    node_id = _nonempty(node_id, "node_id")
    result = _clone(graph)
    if node_id not in result.nodes:
        raise GraphMutationError(f"node does not exist: {node_id!r}")
    incident = [
        edge.id
        for edge in result.edges.values()
        if edge.from_node == node_id or edge.to_node == node_id
    ]
    if incident:
        raise GraphMutationError(
            f"cannot remove node {node_id!r}; remove incident edges first: {incident!r}"
        )
    del result.nodes[node_id]
    result.start_node_ids = [item for item in result.start_node_ids if item != node_id]
    result.end_node_ids = [item for item in result.end_node_ids if item != node_id]
    return _finish(result)


def _edge_from_input(
    edge: AgentEdge | Mapping[str, Any] | None,
    *,
    edge_id: str | None,
    from_node: str | None,
    to_node: str | None,
    fields: Mapping[str, Any],
) -> AgentEdge:
    if isinstance(edge, AgentEdge):
        payload = edge.model_dump(mode="python")
    elif edge is None:
        payload = {}
    else:
        payload = dict(edge)
    for key, value in (
        ("id", edge_id),
        ("from_node", from_node),
        ("to_node", to_node),
    ):
        if value is not None:
            payload[key] = value
    payload.update(fields)
    if "id" not in payload or "from_node" not in payload or "to_node" not in payload:
        raise GraphMutationError("edge id, from_node, and to_node are required")
    if "condition" in payload:
        payload["condition"] = _slot_value(payload["condition"])
    if "evidence" in payload:
        payload["evidence"] = _evidence_list(payload["evidence"])
    try:
        return AgentEdge.model_validate(payload)
    except (TypeError, ValidationError) as exc:
        raise GraphMutationError("invalid AgentEdge") from exc


def add_edge(
    graph: AgentGraph | Mapping[str, Any],
    edge: AgentEdge | Mapping[str, Any] | str | None = None,
    *,
    edge_id: str | None = None,
    from_node: str | None = None,
    to_node: str | None = None,
    **fields: Any,
) -> AgentGraph:
    """Return a graph with one directed edge between existing nodes."""
    if isinstance(edge, str):
        if edge_id is not None:
            raise GraphMutationError("edge ID was supplied twice")
        edge_id = edge
        edge = None
    value = _edge_from_input(
        edge,
        edge_id=edge_id,
        from_node=from_node,
        to_node=to_node,
        fields=fields,
    )
    result = _clone(graph)
    if value.id in result.edges:
        raise GraphMutationError(f"edge already exists: {value.id!r}")
    if value.from_node not in result.nodes:
        raise GraphMutationError(f"edge from_node does not exist: {value.from_node!r}")
    if value.to_node not in result.nodes:
        raise GraphMutationError(f"edge to_node does not exist: {value.to_node!r}")
    result.edges[value.id] = value
    return _finish(result)


def update_edge(
    graph: AgentGraph | Mapping[str, Any],
    edge_id: str,
    edge: AgentEdge | Mapping[str, Any] | None = None,
    *,
    updates: Mapping[str, Any] | None = None,
    **fields: Any,
) -> AgentGraph:
    """Return a graph with one existing edge replaced or partially updated."""
    edge_id = _nonempty(edge_id, "edge_id")
    result = _clone(graph)
    if edge_id not in result.edges:
        raise GraphMutationError(f"edge does not exist: {edge_id!r}")
    if edge is not None and isinstance(edge, Mapping) and "id" not in edge:
        patch = dict(edge)
        patch.update(dict(updates or {}))
        patch.update(fields)
        payload = result.edges[edge_id].model_dump(mode="python")
        payload.update(patch)
        replacement = _edge_from_input(
            payload,
            edge_id=None,
            from_node=None,
            to_node=None,
            fields={},
        )
        if replacement.id != edge_id:
            raise GraphMutationError("edge ID cannot be changed by update_edge")
        result.edges[edge_id] = replacement
    elif edge is not None:
        replacement = _edge_from_input(
            edge,
            edge_id=None,
            from_node=None,
            to_node=None,
            fields={},
        )
        if replacement.id != edge_id:
            raise GraphMutationError("replacement edge id does not match edge_id")
        patch = dict(updates or {})
        patch.update(fields)
        if patch:
            payload = replacement.model_dump(mode="python")
            payload.update(patch)
            replacement = _edge_from_input(
                payload,
                edge_id=None,
                from_node=None,
                to_node=None,
                fields={},
            )
        result.edges[edge_id] = replacement
    else:
        patch = dict(updates or {})
        patch.update(fields)
        if not patch:
            raise GraphMutationError("edge update requires at least one field")
        payload = result.edges[edge_id].model_dump(mode="python")
        payload.update(patch)
        try:
            result.edges[edge_id] = _edge_from_input(
                payload,
                edge_id=None,
                from_node=None,
                to_node=None,
                fields={},
            )
        except (TypeError, ValidationError, GraphMutationError) as exc:
            raise GraphMutationError("invalid edge update") from exc

    updated = result.edges[edge_id]
    if updated.id != edge_id:
        raise GraphMutationError("edge ID cannot be changed by update_edge")
    if updated.from_node not in result.nodes:
        raise GraphMutationError(
            f"edge from_node does not exist: {updated.from_node!r}"
        )
    if updated.to_node not in result.nodes:
        raise GraphMutationError(f"edge to_node does not exist: {updated.to_node!r}")
    return _finish(result)


def remove_edge(
    graph: AgentGraph | Mapping[str, Any],
    edge_id: str,
) -> AgentGraph:
    """Return a graph without one existing edge."""
    edge_id = _nonempty(edge_id, "edge_id")
    result = _clone(graph)
    if edge_id not in result.edges:
        raise GraphMutationError(f"edge does not exist: {edge_id!r}")
    del result.edges[edge_id]
    return _finish(result)


def _concept_from_input(
    concept: AgentConcept | Mapping[str, Any] | None,
    *,
    concept_id: str | None,
    kind: str | None,
    display_label: str | None,
    description: str | None,
    mentions: Iterable[EvidenceRef | Mapping[str, Any]] | None,
) -> AgentConcept:
    if isinstance(concept, AgentConcept):
        payload = concept.model_dump(mode="python")
    elif concept is None:
        payload = {}
    else:
        payload = dict(concept)
    for key, value in (
        ("id", concept_id),
        ("kind", kind),
        ("display_label", display_label),
        ("description", description),
    ):
        if value is not None:
            payload[key] = value
    if mentions is not None:
        payload["mentions"] = list(mentions)
    if "id" not in payload or "kind" not in payload or "display_label" not in payload:
        raise GraphMutationError("concept id, kind, and display_label are required")
    try:
        value = AgentConcept.model_validate(payload)
    except (TypeError, ValidationError) as exc:
        raise GraphMutationError("invalid AgentConcept") from exc
    _nonempty(value.id, "concept id")
    _nonempty(value.display_label, "display_label")
    return value


def define_concept(
    graph: AgentGraph | Mapping[str, Any],
    concept: AgentConcept | Mapping[str, Any] | str | None = None,
    *,
    concept_id: str | None = None,
    kind: str | None = None,
    display_label: str | None = None,
    description: str | None = None,
    mentions: Iterable[EvidenceRef | Mapping[str, Any]] | None = None,
) -> AgentGraph:
    """Add a new glossary concept to the Agent graph."""
    if isinstance(concept, str):
        if concept_id is not None:
            raise GraphMutationError("concept ID was supplied twice")
        concept_id = concept
        concept = None
    value = _concept_from_input(
        concept,
        concept_id=concept_id,
        kind=kind,
        display_label=display_label,
        description=description,
        mentions=mentions,
    )
    result = _clone(graph)
    if value.id in result.concepts:
        raise GraphMutationError(f"concept already exists: {value.id!r}")
    result.concepts[value.id] = value
    return _finish(result)


def update_concept(
    graph: AgentGraph | Mapping[str, Any],
    concept_id: str,
    concept: AgentConcept | Mapping[str, Any] | None = None,
    *,
    updates: Mapping[str, Any] | None = None,
    **fields: Any,
) -> AgentGraph:
    """Update one existing glossary concept."""
    concept_id = _nonempty(concept_id, "concept_id")
    result = _clone(graph)
    if concept_id not in result.concepts:
        raise GraphMutationError(f"concept does not exist: {concept_id!r}")
    patch = dict(updates or {})
    patch.update(fields)
    if concept is not None and isinstance(concept, Mapping) and "id" not in concept:
        patch = {**dict(concept), **patch}
        payload = result.concepts[concept_id].model_dump(mode="python")
        payload.update(patch)
    elif concept is not None:
        replacement = _concept_from_input(
            concept,
            concept_id=None,
            kind=None,
            display_label=None,
            description=None,
            mentions=None,
        )
        if replacement.id != concept_id:
            raise GraphMutationError("replacement concept id does not match concept_id")
        payload = replacement.model_dump(mode="python")
        payload.update(patch)
    else:
        if not patch:
            raise GraphMutationError("concept update requires at least one field")
        payload = result.concepts[concept_id].model_dump(mode="python")
        payload.update(patch)
    try:
        replacement = AgentConcept.model_validate(payload)
    except (TypeError, ValidationError) as exc:
        raise GraphMutationError("invalid concept update") from exc
    _nonempty(replacement.id, "concept id")
    _nonempty(replacement.display_label, "display_label")
    if replacement.id != concept_id:
        raise GraphMutationError("concept ID cannot be changed by update_concept")
    result.concepts[concept_id] = replacement
    return _finish(result)


def remove_concept(
    graph: AgentGraph | Mapping[str, Any],
    concept_id: str,
) -> AgentGraph:
    """Remove an unreferenced glossary concept."""
    concept_id = _nonempty(concept_id, "concept_id")
    result = _clone(graph)
    if concept_id not in result.concepts:
        raise GraphMutationError(f"concept does not exist: {concept_id!r}")
    references: list[str] = []
    for node in result.nodes.values():
        for property_name in _NODE_PROPERTIES:
            if any(ref.concept_id == concept_id for ref in node.refs(property_name)):
                references.append(f"node:{node.id}:{property_name}")
    for edge in result.edges.values():
        if any(
            ref.concept_id == concept_id for ref in _refs_from_value(edge.condition)
        ):
            references.append(f"edge:{edge.id}:condition")
    if references:
        raise GraphMutationError(
            f"cannot remove referenced concept {concept_id!r}: {references!r}"
        )
    del result.concepts[concept_id]
    return _finish(result)


def set_node_property(
    graph: AgentGraph | Mapping[str, Any],
    node_id: str,
    property_name: str,
    value: Any,
) -> AgentGraph:
    """Set one node slot to a value or an explicit epistemic marker."""
    node_id = _nonempty(node_id, "node_id")
    property_name = _property_name(property_name, _NODE_PROPERTIES)
    result = _clone(graph)
    node = result.nodes.get(node_id)
    if node is None:
        raise GraphMutationError(f"node does not exist: {node_id!r}")
    parsed = _slot_value(value, list_slot=property_name in ("reads", "writes"))
    for ref in _refs_from_value(parsed):
        if ref.concept_id not in result.concepts:
            raise GraphMutationError(
                f"{property_name} references unknown concept {ref.concept_id!r}"
            )
    attribute = "necessity_rationale" if property_name == "rationale" else property_name
    payload = node.model_dump(mode="python")
    payload[attribute] = parsed
    try:
        result.nodes[node_id] = AgentNode.model_validate(payload)
    except (TypeError, ValidationError) as exc:
        raise GraphMutationError("invalid node property value") from exc
    return _finish(result)


def set_node_absent(
    graph: AgentGraph | Mapping[str, Any],
    node_id: str,
    property_name: str,
    *,
    evidence: Iterable[EvidenceRef | Mapping[str, Any]] = (),
) -> AgentGraph:
    """Set a node slot to explicit ``ABSENT``."""
    return set_node_property(
        graph,
        node_id,
        property_name,
        AbsentType(evidence=_evidence_list(evidence)),
    )


def set_node_dont_know(
    graph: AgentGraph | Mapping[str, Any],
    node_id: str,
    property_name: str,
    *,
    evidence: Iterable[EvidenceRef | Mapping[str, Any]] = (),
) -> AgentGraph:
    """Set a node slot to explicit ``DONT_KNOW``."""
    return set_node_property(
        graph,
        node_id,
        property_name,
        DontKnowType(evidence=_evidence_list(evidence)),
    )


def set_edge_condition(
    graph: AgentGraph | Mapping[str, Any],
    edge_id: str,
    value: Any,
) -> AgentGraph:
    """Set an edge condition to a value or an explicit epistemic marker."""
    edge_id = _nonempty(edge_id, "edge_id")
    result = _clone(graph)
    edge = result.edges.get(edge_id)
    if edge is None:
        raise GraphMutationError(f"edge does not exist: {edge_id!r}")
    parsed = _slot_value(value)
    for ref in _refs_from_value(parsed):
        if ref.concept_id not in result.concepts:
            raise GraphMutationError(
                f"condition references unknown concept {ref.concept_id!r}"
            )
    payload = edge.model_dump(mode="python")
    payload["condition"] = parsed
    try:
        result.edges[edge_id] = AgentEdge.model_validate(payload)
    except (TypeError, ValidationError) as exc:
        raise GraphMutationError("invalid edge condition") from exc
    return _finish(result)


def set_edge_condition_absent(
    graph: AgentGraph | Mapping[str, Any],
    edge_id: str,
    *,
    evidence: Iterable[EvidenceRef | Mapping[str, Any]] = (),
) -> AgentGraph:
    """Set an edge condition to explicit ``ABSENT``."""
    return set_edge_condition(
        graph,
        edge_id,
        AbsentType(evidence=_evidence_list(evidence)),
    )


def set_edge_condition_dont_know(
    graph: AgentGraph | Mapping[str, Any],
    edge_id: str,
    *,
    evidence: Iterable[EvidenceRef | Mapping[str, Any]] = (),
) -> AgentGraph:
    """Set an edge condition to explicit ``DONT_KNOW``."""
    return set_edge_condition(
        graph,
        edge_id,
        DontKnowType(evidence=_evidence_list(evidence)),
    )


def _refs_from_value(value: Any) -> list[ConceptRef]:
    if isinstance(value, ConceptRef):
        return [value]
    if isinstance(value, list):
        return list(value)
    return []


def set_start_nodes(
    graph: AgentGraph | Mapping[str, Any],
    node_ids: Iterable[str],
) -> AgentGraph:
    """Set validated Agent graph entry endpoints."""
    return _set_endpoints(graph, node_ids, field_name="start_node_ids")


def set_end_nodes(
    graph: AgentGraph | Mapping[str, Any],
    node_ids: Iterable[str],
) -> AgentGraph:
    """Set validated Agent graph exit endpoints."""
    return _set_endpoints(graph, node_ids, field_name="end_node_ids")


def _set_endpoints(
    graph: AgentGraph | Mapping[str, Any],
    node_ids: Iterable[str],
    *,
    field_name: Literal["start_node_ids", "end_node_ids"],
) -> AgentGraph:
    values = [_nonempty(item, "endpoint node id") for item in node_ids]
    if len(values) != len(set(values)):
        raise GraphMutationError("endpoint node IDs must be unique")
    result = _clone(graph)
    missing = [item for item in values if item not in result.nodes]
    if missing:
        raise GraphMutationError(f"endpoint node IDs do not exist: {missing!r}")
    setattr(result, field_name, values)
    return _finish(result)


def _parse_target(target: str) -> tuple[str, ...]:
    target = _nonempty(target, "evidence target")
    return tuple(target.split(":"))


def _append_ref_evidence(ref: ConceptRef, evidence: EvidenceRef) -> ConceptRef:
    return ref.model_copy(update={"evidence": [*ref.evidence, evidence]})


def _attach_slot_evidence(
    node: AgentNode,
    property_name: str,
    evidence: EvidenceRef,
    *,
    concept_id: str | None,
) -> Any:
    value = node.slot_value(property_name)
    if isinstance(value, (UnsetType,)):
        raise GraphMutationError(
            f"cannot attach evidence to unasserted UNSET slot {property_name!r}"
        )
    if isinstance(value, (AbsentType, DontKnowType)):
        return value.model_copy(update={"evidence": [*value.evidence, evidence]})
    if isinstance(value, ConceptRef):
        if concept_id is not None and value.concept_id != concept_id:
            raise GraphMutationError(f"slot does not contain concept {concept_id!r}")
        return _append_ref_evidence(value, evidence)
    if isinstance(value, list):
        if concept_id is None:
            if len(value) != 1:
                raise GraphMutationError(
                    "a list slot with multiple concepts requires a concept target"
                )
            return [_append_ref_evidence(value[0], evidence)]
        found = False
        updated: list[ConceptRef] = []
        for ref in value:
            if ref.concept_id == concept_id:
                updated.append(_append_ref_evidence(ref, evidence))
                found = True
            else:
                updated.append(ref)
        if not found:
            raise GraphMutationError(f"slot does not contain concept {concept_id!r}")
        return updated
    raise GraphMutationError(f"slot {property_name!r} cannot carry evidence")


def attach_evidence(
    graph: AgentGraph | Mapping[str, Any],
    target: str | None = None,
    evidence: EvidenceRef | Mapping[str, Any] | None = None,
    *,
    node_id: str | None = None,
    edge_id: str | None = None,
    property_name: str | None = None,
    concept_id: str | None = None,
    observation_ids: Iterable[str] | None = None,
    observation_texts: Mapping[str, str] | None = None,
    observation_id: str | None = None,
    quote: str | None = None,
    occurrence: int = 0,
) -> AgentGraph:
    """Attach one exact ``EvidenceRef`` to a graph-local target.

    Targets are ``node:<id>:<property>`` (or add ``:<concept_id>`` for a
    list-element), ``edge:<id>``, ``edge:<id>:condition``, or
    ``concept:<id>``.  When ``observation_ids``/``observation_texts`` are
    supplied, the reference ID and optional quote are checked against that
    explicit runtime ledger.
    """
    if target is None:
        if node_id is not None and property_name is not None:
            target = f"node:{node_id}:{property_name}"
        elif edge_id is not None:
            if property_name is None:
                target = f"edge:{edge_id}"
            elif _property_name(property_name, _EDGE_PROPERTIES) == "condition":
                target = f"edge:{edge_id}:condition"
        elif concept_id is not None:
            target = f"concept:{concept_id}"
        if target is None:
            raise GraphMutationError(
                "edge evidence property must be 'condition' when supplied"
            )
    elif property_name is not None and target.startswith("edge:"):
        if _property_name(property_name, _EDGE_PROPERTIES) != "condition":
            raise GraphMutationError("edge evidence property must be 'condition'")
        if len(target.split(":")) == 2:
            target = f"{target}:condition"
    if evidence is None:
        if observation_id is None:
            raise GraphMutationError(
                "observation_id is required when evidence is omitted"
            )
        evidence = EvidenceRef(
            observation_id=_nonempty(observation_id, "observation_id"),
            quote=quote,
            occurrence=occurrence,
        )
    item = _evidence(evidence)
    if observation_ids is not None and item.observation_id not in set(observation_ids):
        raise GraphMutationError(
            f"evidence references unknown observation {item.observation_id!r}"
        )
    if observation_texts is not None:
        text = observation_texts.get(item.observation_id)
        if text is None:
            raise GraphMutationError(
                f"evidence references unknown observation {item.observation_id!r}"
            )
        if item.quote and item.resolve_span(text) is None:
            raise GraphMutationError(
                "evidence quote is not an exact span of the referenced observation"
            )

    parts = _parse_target(target)
    result = _clone(graph)
    if not parts:
        raise GraphMutationError("invalid evidence target")
    kind = parts[0]
    if kind == "node":
        if len(parts) not in (3, 4):
            raise GraphMutationError(
                "node evidence target must be node:<id>:<property>[:<concept_id>]"
            )
        target_node_id, target_property = (
            parts[1],
            _property_name(parts[2], _NODE_PROPERTIES),
        )
        node = result.nodes.get(target_node_id)
        if node is None:
            raise GraphMutationError(f"node does not exist: {target_node_id!r}")
        selected_concept = parts[3] if len(parts) == 4 else concept_id
        updated_value = _attach_slot_evidence(
            node,
            target_property,
            item,
            concept_id=selected_concept,
        )
        attribute = (
            "necessity_rationale" if target_property == "rationale" else target_property
        )
        payload = node.model_dump(mode="python")
        payload[attribute] = updated_value
        try:
            result.nodes[target_node_id] = AgentNode.model_validate(payload)
        except (TypeError, ValidationError) as exc:
            raise GraphMutationError("invalid node evidence attachment") from exc
        return _finish(result)

    if kind == "edge":
        if len(parts) not in (2, 3):
            raise GraphMutationError(
                "edge evidence target must be edge:<id>[:condition]"
            )
        target_edge_id = parts[1]
        edge = result.edges.get(target_edge_id)
        if edge is None:
            raise GraphMutationError(f"edge does not exist: {target_edge_id!r}")
        if len(parts) == 2:
            result.edges[target_edge_id] = edge.model_copy(
                update={"evidence": [*edge.evidence, item]}
            )
            return _finish(result)
        if parts[2] != "condition":
            raise GraphMutationError("edge evidence property must be 'condition'")
        updated_value = _attach_condition_evidence(edge, item)
        result.edges[target_edge_id] = edge.model_copy(
            update={"condition": updated_value}
        )
        return _finish(result)

    if kind == "concept":
        if len(parts) != 2:
            raise GraphMutationError("concept evidence target must be concept:<id>")
        target_concept_id = parts[1]
        concept = result.concepts.get(target_concept_id)
        if concept is None:
            raise GraphMutationError(f"concept does not exist: {target_concept_id!r}")
        result.concepts[target_concept_id] = concept.model_copy(
            update={"mentions": [*concept.mentions, item]}
        )
        return _finish(result)

    raise GraphMutationError(f"unknown evidence target kind: {kind!r}")


def _attach_condition_evidence(edge: AgentEdge, evidence: EvidenceRef) -> Any:
    value = edge.condition
    if isinstance(value, UnsetType):
        raise GraphMutationError("cannot attach evidence to UNSET edge condition")
    if isinstance(value, (AbsentType, DontKnowType)):
        return value.model_copy(update={"evidence": [*value.evidence, evidence]})
    if isinstance(value, ConceptRef):
        return _append_ref_evidence(value, evidence)
    raise GraphMutationError("edge condition cannot carry evidence")


# Descriptive aliases make the operation surface easy to discover without
# introducing a second graph implementation.
add_agent_node = add_node
update_agent_node = update_node
remove_agent_node = remove_node
add_agent_edge = add_edge
update_agent_edge = update_edge
remove_agent_edge = remove_edge
add_concept = define_concept
define_agent_concept = define_concept
add_agent_concept = define_concept
update_agent_concept = update_concept
remove_agent_concept = remove_concept
set_agent_node_property = set_node_property
set_agent_edge_condition = set_edge_condition
set_node_slot = set_node_property
set_edge_slot = set_edge_condition
attach_evidence_ref = attach_evidence
add_graph_node = add_node
update_graph_node = update_node
remove_graph_node = remove_node
add_graph_edge = add_edge
update_graph_edge = update_edge
remove_graph_edge = remove_edge
define_graph_concept = define_concept
update_graph_concept = update_concept
remove_graph_concept = remove_concept


__all__ = [
    "GraphMutationError",
    "add_agent_concept",
    "add_agent_edge",
    "add_agent_node",
    "add_concept",
    "add_edge",
    "add_graph_edge",
    "add_graph_node",
    "add_node",
    "attach_evidence",
    "attach_evidence_ref",
    "define_agent_concept",
    "define_concept",
    "define_graph_concept",
    "remove_agent_concept",
    "remove_agent_edge",
    "remove_agent_node",
    "remove_concept",
    "remove_edge",
    "remove_graph_concept",
    "remove_graph_edge",
    "remove_graph_node",
    "remove_node",
    "set_agent_edge_condition",
    "set_agent_node_property",
    "set_edge_condition",
    "set_edge_condition_absent",
    "set_edge_slot",
    "set_edge_condition_dont_know",
    "set_end_nodes",
    "set_node_absent",
    "set_node_dont_know",
    "set_node_property",
    "set_node_slot",
    "set_start_nodes",
    "update_agent_concept",
    "update_agent_edge",
    "update_agent_node",
    "update_concept",
    "update_edge",
    "update_graph_concept",
    "update_graph_edge",
    "update_graph_node",
    "update_node",
]
