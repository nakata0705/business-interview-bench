"""A minimal private stakeholder knowledge world model.

This module describes what a future stakeholder simulator may know.  It does
not project a Truth graph, sample forgetting, render prompts, or store
conversation annotations.  Truth mappings are retained as private evaluator
metadata, while all graph element and concept IDs in the world model are
stakeholder-local.
"""

# The workspace-level auxiliary Pyright runner can miss freshly added sibling
# modules; project-level ``uv run pyright`` remains the authoritative check.
# pyright: reportMissingImports=false

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, TypeAlias

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from business_interview.models import (
    STRUCTURAL_SINK_ID,
    STRUCTURAL_SOURCE_ID,
    ConceptKind,
    canonical_structure_errors,
)

KnowledgeEdgeKind = Literal["business", "structural_boundary", "shortcut"]
StructuralRole = Literal["source", "sink"]


class KnowledgeDontKnowType(BaseModel):
    """Explicit unknown value, distinct from known absence (``None``)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    state: Literal["dont_know"] = "dont_know"


DONT_KNOW = KnowledgeDontKnowType()


def _coerce_dont_know(value: object) -> object:
    """Normalize compatible marker objects without importing evaluator state."""
    if isinstance(value, KnowledgeDontKnowType):
        return value
    if (isinstance(value, Mapping) and value.get("state") == "dont_know") or getattr(
        value, "state", None
    ) == "dont_know":
        return DONT_KNOW
    return value


def is_dont_know(value: object) -> bool:
    """Return whether a world-model slot is explicitly unknown."""
    return isinstance(value, KnowledgeDontKnowType)


def is_known_absent(value: object) -> bool:
    """Return whether a world-model slot is explicitly known to be absent."""
    return value is None


class KnowledgeConceptRef(BaseModel):
    """A value-bearing reference to a stakeholder-local concept."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    concept_id: str = Field(min_length=1)

    @field_validator("concept_id")
    @classmethod
    def _local_id_is_opaque_shape(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("concept_id must not be empty")
        if ":" in value:
            raise ValueError("stakeholder-local concept IDs must not contain ':'")
        return value


KnowledgeSlot: TypeAlias = KnowledgeConceptRef | None | KnowledgeDontKnowType
KnowledgeListSlot: TypeAlias = list[KnowledgeConceptRef] | None | KnowledgeDontKnowType


def _local_id(value: str, field_name: str) -> str:
    if not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    if ":" in value:
        raise ValueError(f"{field_name} must not contain ':'")
    return value


def _ref_sort_key(value: object) -> str:
    if isinstance(value, Mapping):
        return str(value.get("concept_id", ""))
    return str(getattr(value, "concept_id", ""))


def _normalize_reference_lists(value: object) -> object:
    if not isinstance(value, Mapping):
        return value
    payload = dict(value)
    for axis in ("reads", "writes"):
        raw = payload.get(axis)
        if isinstance(raw, (list, tuple, set, frozenset)):
            payload[axis] = sorted(raw, key=_ref_sort_key)
    return payload


def _normalize_terms(value: object) -> object:
    if not isinstance(value, Mapping):
        return value
    payload = dict(value)
    raw = payload.get("terms")
    if isinstance(raw, (list, tuple, set, frozenset)) and all(
        isinstance(term, str) for term in raw
    ):
        payload["terms"] = tuple(sorted(set(raw)))
    return payload


def _normalize_map_fields(value: object, fields: tuple[str, ...]) -> object:
    if not isinstance(value, Mapping):
        return value
    payload = dict(value)
    for field_name in fields:
        raw = payload.get(field_name)
        if isinstance(raw, Mapping) and all(isinstance(key, str) for key in raw):
            payload[field_name] = {key: raw[key] for key in sorted(raw)}
    return payload


class StakeholderKnowledgeConcept(BaseModel):
    """One local concept and its private Truth mapping.

    ``description`` and ``terms`` are independently known or unknown.  The
    local ID is the only ID a future simulator should expose; Truth mapping is
    retained for private projection/evaluation code.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    truth_concept_id: str = Field(
        min_length=1,
        description="Private local-concept ID to Truth-concept ID mapping.",
    )
    kind: ConceptKind
    description: str | KnowledgeDontKnowType = Field(default_factory=lambda: DONT_KNOW)
    terms: tuple[str, ...] | KnowledgeDontKnowType = Field(
        default_factory=lambda: DONT_KNOW
    )

    @model_validator(mode="before")
    @classmethod
    def _normalize_input(cls, value: object) -> object:
        normalized = _normalize_terms(value)
        if not isinstance(normalized, Mapping):
            return normalized
        payload = dict(normalized)
        for field_name in ("description", "terms"):
            if field_name in payload:
                payload[field_name] = _coerce_dont_know(payload[field_name])
        return payload

    @field_validator("id")
    @classmethod
    def _id_is_local(cls, value: str) -> str:
        return _local_id(value, "concept id")

    @field_validator("truth_concept_id")
    @classmethod
    def _truth_id_is_nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("truth_concept_id must not be empty")
        return value

    @field_validator("terms")
    @classmethod
    def _terms_are_nonempty(
        cls, value: tuple[str, ...] | KnowledgeDontKnowType
    ) -> tuple[str, ...] | KnowledgeDontKnowType:
        if isinstance(value, KnowledgeDontKnowType):
            return value
        if any(not term.strip() for term in value):
            raise ValueError("concept terms must not be empty")
        return value

    def has_description(self) -> bool:
        return not is_dont_know(self.description)

    def has_terms(self) -> bool:
        return not is_dont_know(self.terms)


class StakeholderNode(BaseModel):
    """One local node with explicit value/absent/unknown property slots."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    activity: KnowledgeSlot = None
    actor: KnowledgeSlot = None
    system: KnowledgeSlot = None
    reads: KnowledgeListSlot = None
    writes: KnowledgeListSlot = None
    rationale: KnowledgeSlot = Field(
        default=None,
        validation_alias=AliasChoices("rationale", "necessity_rationale"),
    )
    structural: bool = False
    structural_role: StructuralRole | None = None
    protected: bool = False

    @model_validator(mode="before")
    @classmethod
    def _normalize_input(cls, value: object) -> object:
        normalized = _normalize_reference_lists(value)
        if not isinstance(normalized, Mapping):
            return normalized
        payload = dict(normalized)
        for field_name in (
            "activity",
            "actor",
            "system",
            "reads",
            "writes",
            "rationale",
            "necessity_rationale",
        ):
            if field_name in payload:
                payload[field_name] = _coerce_dont_know(payload[field_name])
        return payload

    @field_validator("id")
    @classmethod
    def _id_is_local(cls, value: str) -> str:
        return _local_id(value, "node id")

    @property
    def is_structural(self) -> bool:
        return self.structural or self.structural_role is not None

    @property
    def necessity_rationale(self) -> KnowledgeSlot:
        """Source-shaped read alias; serialized field name remains rationale."""
        return self.rationale

    def slot_value(self, property_name: str) -> KnowledgeSlot | KnowledgeListSlot:
        return getattr(self, property_name)

    def refs(self, property_name: str) -> list[KnowledgeConceptRef]:
        value = self.slot_value(property_name)
        if isinstance(value, KnowledgeConceptRef):
            return [value]
        if isinstance(value, list):
            return list(value)
        return []


class ShortcutProvenance(BaseModel):
    """Private provenance attached to a derived local shortcut edge."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    is_shortcut: bool = True
    contracted_nodes: tuple[str, ...] = Field(default_factory=tuple)
    derived_from_edges: tuple[str, ...] = Field(default_factory=tuple)


class StakeholderEdge(BaseModel):
    """One local edge, including protected boundary/shortcut metadata."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    from_node: str = Field(min_length=1)
    to_node: str = Field(min_length=1)
    condition: KnowledgeSlot = None
    edge_kind: KnowledgeEdgeKind = "business"
    structural_only: bool = False
    protected: bool = False
    is_shortcut: bool = False
    contracted_nodes: tuple[str, ...] = Field(default_factory=tuple)
    derived_from_edges: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="before")
    @classmethod
    def _normalize_input(cls, value: object) -> object:
        if not isinstance(value, Mapping):
            return value
        payload = dict(value)
        if "condition" in payload:
            payload["condition"] = _coerce_dont_know(payload["condition"])
        return payload

    @field_validator("id", "from_node", "to_node")
    @classmethod
    def _ids_are_local(cls, value: str, info) -> str:
        return _local_id(value, info.field_name)

    @property
    def is_structural(self) -> bool:
        return self.structural_only or self.edge_kind == "structural_boundary"


_NODE_PROPERTIES = ("activity", "actor", "system", "reads", "writes", "rationale")


def _slot_refs(value: object) -> list[KnowledgeConceptRef]:
    if isinstance(value, KnowledgeConceptRef):
        return [value]
    if isinstance(value, list):
        return list(value)
    return []


def _graph_semantic_ids(graph: StakeholderKnowledgeGraph) -> set[str]:
    ids: set[str] = set()
    for node_id, node in graph.nodes.items():
        ids.add(f"node:{node_id}")
        ids.update(f"node:{node_id}:{prop}" for prop in _NODE_PROPERTIES)
        for prop in ("reads", "writes"):
            ids.update(
                f"node:{node_id}:{prop}:{ref.concept_id}" for ref in node.refs(prop)
            )
    for edge_id in graph.edges:
        ids.add(f"edge:{edge_id}")
        ids.add(f"edge:{edge_id}:condition")
    ids.update(graph.concepts)
    return ids


class StakeholderKnowledgeGraph(BaseModel):
    """The private local graph seen by a future stakeholder simulator."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = "knowledge"
    name: str = ""
    nodes: dict[str, StakeholderNode] = Field(default_factory=dict)
    edges: dict[str, StakeholderEdge] = Field(default_factory=dict)
    concepts: dict[str, StakeholderKnowledgeConcept] = Field(default_factory=dict)
    source_node_id: str = STRUCTURAL_SOURCE_ID
    sink_node_id: str = STRUCTURAL_SINK_ID
    node_truth_ids: dict[str, str] = Field(
        default_factory=dict,
        description="Private local-node ID to Truth-node ID mappings.",
    )
    edge_truth_ids: dict[str, str] = Field(
        default_factory=dict,
        description="Private local-edge ID to Truth-edge ID mappings.",
    )
    shortcut_provenance: dict[str, ShortcutProvenance] = Field(
        default_factory=dict,
        description="Private provenance for local shortcut edges.",
    )

    @model_validator(mode="before")
    @classmethod
    def _normalize_input(cls, value: object) -> object:
        return _normalize_map_fields(
            value,
            (
                "nodes",
                "edges",
                "concepts",
                "node_truth_ids",
                "edge_truth_ids",
                "shortcut_provenance",
            ),
        )

    def semantic_ids(self) -> set[str]:
        """Return every addressable graph/concept ID in the local namespace."""
        return _graph_semantic_ids(self)

    def structure_errors(self) -> list[str]:
        """Return local-reference, provenance, and canonical topology errors."""
        errors = list(canonical_structure_errors(self))
        for key, node in self.nodes.items():
            if key != node.id:
                errors.append(f"node mapping key does not match node.id: {key}")
            for property_name in _NODE_PROPERTIES:
                refs = _slot_refs(node.slot_value(property_name))
                ref_ids = [ref.concept_id for ref in refs]
                if len(ref_ids) != len(set(ref_ids)):
                    errors.append(
                        f"node {key}: {property_name} has duplicate local concept "
                        "references"
                    )
                for ref in refs:
                    if ref.concept_id not in self.concepts:
                        errors.append(
                            f"node {key}: {property_name} references unknown "
                            f"concept {ref.concept_id!r}"
                        )
        for key, edge in self.edges.items():
            if key != edge.id:
                errors.append(f"edge mapping key does not match edge.id: {key}")
            for ref in _slot_refs(edge.condition):
                if ref.concept_id not in self.concepts:
                    errors.append(
                        f"edge {key}: condition references unknown concept "
                        f"{ref.concept_id!r}"
                    )
        for key, concept in self.concepts.items():
            if key != concept.id:
                errors.append(f"concept mapping key does not match concept.id: {key}")

        all_truth_ids = set(self.node_truth_ids.values())
        all_truth_ids.update(self.edge_truth_ids.values())
        all_truth_ids.update(
            concept.truth_concept_id for concept in self.concepts.values()
        )
        for local_id in (*self.nodes, *self.edges, *self.concepts):
            if local_id in {STRUCTURAL_SOURCE_ID, STRUCTURAL_SINK_ID}:
                continue
            if local_id in all_truth_ids:
                errors.append(f"local ID must be opaque, not Truth ID: {local_id}")

        for local_id, truth_id in self.node_truth_ids.items():
            if local_id not in self.nodes:
                errors.append(
                    f"node Truth mapping references unknown local node: {local_id}"
                )
            if not truth_id.strip():
                errors.append(f"node Truth mapping is empty: {local_id}")
            if local_id == truth_id:
                errors.append(f"local node id must be opaque, not Truth id: {local_id}")
        for local_id, truth_id in self.edge_truth_ids.items():
            if local_id not in self.edges:
                errors.append(
                    f"edge Truth mapping references unknown local edge: {local_id}"
                )
            if not truth_id.strip():
                errors.append(f"edge Truth mapping is empty: {local_id}")
            if local_id == truth_id:
                errors.append(f"local edge id must be opaque, not Truth id: {local_id}")
        for local_id, concept in self.concepts.items():
            if local_id == concept.truth_concept_id:
                errors.append(
                    f"local concept id must be opaque, not Truth id: {local_id}"
                )

        for edge_id, provenance in self.shortcut_provenance.items():
            edge = self.edges.get(edge_id)
            if edge is None:
                errors.append(f"shortcut provenance references unknown edge: {edge_id}")
                continue
            if not edge.is_shortcut:
                errors.append(
                    f"shortcut provenance attached to non-shortcut edge: {edge_id}"
                )
            if not provenance.is_shortcut:
                errors.append(f"shortcut provenance is not marked shortcut: {edge_id}")
            if tuple(edge.contracted_nodes) != tuple(provenance.contracted_nodes):
                errors.append(f"shortcut contracted_nodes disagree for edge: {edge_id}")
            if tuple(edge.derived_from_edges) != tuple(provenance.derived_from_edges):
                errors.append(
                    f"shortcut derived_from_edges disagree for edge: {edge_id}"
                )
        for edge_id, edge in self.edges.items():
            has_metadata = bool(edge.contracted_nodes or edge.derived_from_edges)
            if edge.edge_kind == "shortcut" and not edge.is_shortcut:
                errors.append(f"shortcut edge is not marked shortcut: {edge_id}")
            if edge.is_shortcut and edge.edge_kind not in (
                "shortcut",
                "structural_boundary",
            ):
                errors.append(f"shortcut edge has invalid kind: {edge_id}")
            if edge.is_shortcut and edge_id not in self.shortcut_provenance:
                errors.append(f"shortcut edge has no provenance: {edge_id}")
            if not edge.is_shortcut and has_metadata:
                errors.append(f"non-shortcut edge has shortcut metadata: {edge_id}")
        return errors

    @property
    def is_valid(self) -> bool:
        return not self.structure_errors()

    def semantic_address_ids(self) -> set[str]:
        """Alias emphasizing that ``semantic_ids`` is the address namespace."""
        return self.semantic_ids()

    def resolve(self, semantic_id: str):
        """Resolve one address strictly through the standalone resolver."""
        from .addressing import resolve_semantic_address

        return resolve_semantic_address(self, semantic_id)

    def try_resolve(self, semantic_id: str):
        """Return a resolved address or ``None`` for invalid/unknown input."""
        from .addressing import try_resolve_semantic_address

        return try_resolve_semantic_address(self, semantic_id)

    def referenced_concept_ids(self) -> set[str]:
        """Return local concepts used by known node/edge values."""
        ids: set[str] = set()
        for node in self.nodes.values():
            for property_name in _NODE_PROPERTIES:
                ids.update(
                    ref.concept_id for ref in _slot_refs(node.slot_value(property_name))
                )
        for edge in self.edges.values():
            ids.update(ref.concept_id for ref in _slot_refs(edge.condition))
        return ids


class StakeholderKnowledge(BaseModel):
    """Private world model passed to a future stakeholder simulator."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    graph: StakeholderKnowledgeGraph = Field(default_factory=StakeholderKnowledgeGraph)

    @property
    def concepts(self) -> dict[str, StakeholderKnowledgeConcept]:
        return self.graph.concepts

    def semantic_ids(self) -> set[str]:
        return self.graph.semantic_ids() | set(self.graph.concepts)

    def resolve(self, semantic_id: str):
        return self.graph.resolve(semantic_id)

    def try_resolve(self, semantic_id: str):
        return self.graph.try_resolve(semantic_id)

    def structure_errors(self) -> list[str]:
        return self.graph.structure_errors()

    @property
    def is_valid(self) -> bool:
        return self.graph.is_valid


def validate_stakeholder_knowledge_graph(graph: StakeholderKnowledgeGraph) -> None:
    """Raise ``ValueError`` when a local knowledge graph is not canonical."""
    errors = graph.structure_errors()
    if errors:
        raise ValueError(
            "Invalid stakeholder knowledge graph:\n- " + "\n- ".join(errors)
        )


def validate_stakeholder_knowledge(knowledge: StakeholderKnowledge) -> None:
    """Validate the complete private world model."""
    validate_stakeholder_knowledge_graph(knowledge.graph)


__all__ = [
    "DONT_KNOW",
    "KnowledgeConceptRef",
    "KnowledgeDontKnowType",
    "KnowledgeEdgeKind",
    "KnowledgeListSlot",
    "KnowledgeSlot",
    "ShortcutProvenance",
    "StakeholderEdge",
    "StakeholderKnowledge",
    "StakeholderKnowledgeConcept",
    "StakeholderKnowledgeGraph",
    "StakeholderNode",
    "is_dont_know",
    "is_known_absent",
    "validate_stakeholder_knowledge",
    "validate_stakeholder_knowledge_graph",
]
