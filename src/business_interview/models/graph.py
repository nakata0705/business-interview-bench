"""Pure Truth and Agent graph models.

This module intentionally contains no tau2 runtime state. Conversation state,
tools, simulation, and evaluator integration will be designed separately in
later phases.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .concepts import ConceptKind, ConceptRef, EvidenceRef
from .epistemic import (
    UNSET,
    AbsentType,
    AgentListSlot,
    AgentSlot,
    DontKnowType,
    TruthListSlot,
    TruthSlot,
)

STRUCTURAL_SOURCE_ID = "__tau2_structural_source__"
STRUCTURAL_SINK_ID = "__tau2_structural_sink__"
STRUCTURAL_BOUNDARY_EDGE_PREFIX = "__tau2_structural_boundary__"

StructuralRole = Literal["source", "sink"]
EdgeKind = Literal["business", "structural_boundary", "shortcut"]

_NODE_PROPERTIES = (
    "activity",
    "actor",
    "system",
    "reads",
    "writes",
    "rationale",
)


class TruthConcept(BaseModel):
    """A canonical business concept used by a Truth graph."""

    id: str
    kind: ConceptKind
    description: str = ""
    canonical_terms: list[str] = Field(default_factory=list)


class TruthNode(BaseModel):
    """A complete Truth node; ``None`` means canonical absence."""

    id: str
    activity: TruthSlot = None
    actor: TruthSlot = None
    system: TruthSlot = None
    reads: TruthListSlot = None
    writes: TruthListSlot = None
    necessity_rationale: TruthSlot = None
    structural: bool = False
    structural_role: StructuralRole | None = None
    protected: bool = False

    @property
    def is_structural(self) -> bool:
        return self.structural or self.structural_role is not None

    def refs(self, property_name: str) -> list[ConceptRef]:
        """Return concept references in one Truth slot."""
        value = self.slot_value(property_name)
        if isinstance(value, ConceptRef):
            return [value]
        if isinstance(value, list):
            return list(value)
        return []

    def slot_value(self, property_name: str) -> TruthSlot | TruthListSlot:
        """Read a Truth slot using the public ``rationale`` spelling."""
        attribute = (
            "necessity_rationale" if property_name == "rationale" else property_name
        )
        return getattr(self, attribute)


class TruthEdge(BaseModel):
    """A directed Truth relation; ``condition=None`` is unconditional."""

    id: str
    from_node: str
    to_node: str
    condition: TruthSlot = None
    edge_kind: EdgeKind = "business"
    structural_only: bool = False
    protected: bool = False
    is_shortcut: bool = False
    contracted_nodes: list[str] = Field(default_factory=list)
    derived_from_edges: list[str] = Field(default_factory=list)

    @property
    def is_structural(self) -> bool:
        return self.structural_only or self.edge_kind == "structural_boundary"


class BusinessProcessGraph(BaseModel):
    """Canonical Truth graph container.

    A graph may first be constructed in legacy-style form with only business
    nodes and edges. ``canonicalize_truth_graph`` turns it into the complete
    explicit SOURCE/SINK representation.
    """

    id: str = "graph"
    name: str = ""
    nodes: dict[str, TruthNode] = Field(default_factory=dict)
    edges: dict[str, TruthEdge] = Field(default_factory=dict)
    concepts: dict[str, TruthConcept] = Field(default_factory=dict)
    source_node_id: str = STRUCTURAL_SOURCE_ID
    sink_node_id: str = STRUCTURAL_SINK_ID

    def successors(self, node_id: str) -> list[str]:
        """Return direct successor IDs in insertion order."""
        return [
            edge.to_node for edge in self.edges.values() if edge.from_node == node_id
        ]

    def incoming_edges(self, node_id: str) -> list[str]:
        """Return direct incoming edge IDs in insertion order."""
        return [edge.id for edge in self.edges.values() if edge.to_node == node_id]

    def structure_errors(self) -> list[str]:
        """Return canonical contract errors without raising."""
        from .canonical import canonical_structure_errors

        return canonical_structure_errors(self)

    @property
    def is_valid(self) -> bool:
        return not self.structure_errors()


TruthGraph = BusinessProcessGraph


class AgentConcept(BaseModel):
    """An Agent-local glossary concept."""

    id: str
    kind: ConceptKind
    display_label: str
    description: str = ""
    mentions: list[EvidenceRef] = Field(default_factory=list)


class AgentNode(BaseModel):
    """A revisable Agent hypothesis with four-state slots."""

    id: str
    activity: AgentSlot = Field(default_factory=lambda: UNSET)
    actor: AgentSlot = Field(default_factory=lambda: UNSET)
    system: AgentSlot = Field(default_factory=lambda: UNSET)
    reads: AgentListSlot = Field(default_factory=lambda: UNSET)
    writes: AgentListSlot = Field(default_factory=lambda: UNSET)
    necessity_rationale: AgentSlot = Field(default_factory=lambda: UNSET)

    def refs(self, property_name: str) -> list[ConceptRef]:
        """Return active reference objects in one Agent slot."""
        value = self.slot_value(property_name)
        if isinstance(value, ConceptRef):
            return [value]
        if isinstance(value, list):
            return list(value)
        return []

    def asserted_refs(self, property_name: str) -> list[ConceptRef]:
        return [ref for ref in self.refs(property_name) if ref.asserted]

    def slot_value(self, property_name: str) -> AgentSlot | AgentListSlot:
        attribute = (
            "necessity_rationale" if property_name == "rationale" else property_name
        )
        return getattr(self, attribute)

    def slot_evidence(self, property_name: str) -> list[EvidenceRef]:
        value = self.slot_value(property_name)
        if isinstance(value, (AbsentType, DontKnowType)):
            return list(value.evidence)
        return []


class AgentEdge(BaseModel):
    """A directed Agent hypothesis relation."""

    id: str
    from_node: str
    to_node: str
    condition: AgentSlot = Field(default_factory=lambda: UNSET)
    evidence: list[EvidenceRef] = Field(default_factory=list)

    def condition_evidence(self) -> list[EvidenceRef]:
        if isinstance(self.condition, (AbsentType, DontKnowType)):
            return list(self.condition.evidence)
        return []


class AgentGraph(BaseModel):
    """Agent graph and glossary, independent of tools and orchestration."""

    id: str = "agent_graph"
    name: str = ""
    nodes: dict[str, AgentNode] = Field(default_factory=dict)
    edges: dict[str, AgentEdge] = Field(default_factory=dict)
    concepts: dict[str, AgentConcept] = Field(default_factory=dict)
    start_node_ids: list[str] = Field(default_factory=list)
    end_node_ids: list[str] = Field(default_factory=list)

    def structure_errors(self) -> list[str]:
        """Return local reference/endpoint errors for an Agent graph."""
        errors: list[str] = []
        for node_id, node in self.nodes.items():
            for property_name in _NODE_PROPERTIES:
                for ref in node.refs(property_name):
                    if ref.concept_id not in self.concepts:
                        errors.append(
                            f"node {node_id}: {property_name} references unknown "
                            f"concept {ref.concept_id!r}"
                        )
        for edge_id, edge in self.edges.items():
            if edge.from_node not in self.nodes:
                errors.append(f"edge {edge_id}: from_node not found: {edge.from_node}")
            if edge.to_node not in self.nodes:
                errors.append(f"edge {edge_id}: to_node not found: {edge.to_node}")
            if (
                isinstance(edge.condition, ConceptRef)
                and edge.condition.concept_id not in self.concepts
            ):
                errors.append(
                    f"edge {edge_id}: condition references unknown concept "
                    f"{edge.condition.concept_id!r}"
                )
        for node_id in [*self.start_node_ids, *self.end_node_ids]:
            if node_id not in self.nodes:
                errors.append(f"endpoint node not found: {node_id}")
        return errors

    @property
    def is_valid(self) -> bool:
        return not self.structure_errors()
