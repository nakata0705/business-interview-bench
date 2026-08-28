"""Pure semantic-address parsing and resolution for private knowledge."""

# The workspace-level auxiliary Pyright runner can miss freshly added sibling
# modules; project-level ``uv run pyright`` remains the authoritative check.
# pyright: reportMissingImports=false

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from .knowledge import StakeholderKnowledge, StakeholderKnowledgeGraph

NodeAddressProperty = Literal[
    "activity", "actor", "system", "reads", "writes", "rationale"
]
AddressKind = Literal[
    "node", "node_slot", "node_element", "edge", "edge_slot", "concept"
]

_NODE_PROPERTIES = frozenset(
    ("activity", "actor", "system", "reads", "writes", "rationale")
)
_LIST_PROPERTIES = frozenset(("reads", "writes"))


class SemanticAddressError(ValueError):
    """Base error for malformed or unresolvable private semantic addresses."""

    def __init__(self, address: object, message: str) -> None:
        self.address = address
        super().__init__(f"{message}: {address!r}")


class InvalidSemanticAddressError(SemanticAddressError):
    """Raised when an address does not follow the supported grammar."""


class UnknownSemanticAddressError(SemanticAddressError):
    """Raised when a valid address has no corresponding local object/value."""


@dataclass(frozen=True, slots=True)
class ParsedSemanticAddress:
    """Syntax-only interpretation of one semantic address."""

    raw: str
    kind: AddressKind
    node_id: str | None = None
    edge_id: str | None = None
    property_name: str | None = None
    concept_id: str | None = None


@dataclass(frozen=True, slots=True)
class ResolvedSemanticAddress:
    """One deterministic semantic address resolution result."""

    address: str
    kind: AddressKind
    node_id: str | None = None
    edge_id: str | None = None
    property_name: str | None = None
    concept_id: str | None = None
    value: Any = None
    node: Any = None
    edge: Any = None
    ref: Any = None
    concept: Any = None


def parse_semantic_address(address: str) -> ParsedSemanticAddress:
    """Parse the supported address grammar without consulting a graph."""
    if not isinstance(address, str) or not address.strip():
        raise InvalidSemanticAddressError(address, "semantic address must be non-empty")

    if address.startswith("node:"):
        parts = address.split(":")
        if len(parts) == 2 and parts[1]:
            return ParsedSemanticAddress(raw=address, kind="node", node_id=parts[1])
        if len(parts) == 3 and parts[1] and parts[2] in _NODE_PROPERTIES:
            return ParsedSemanticAddress(
                raw=address,
                kind="node_slot",
                node_id=parts[1],
                property_name=parts[2],
            )
        if len(parts) == 4 and parts[1] and parts[2] in _LIST_PROPERTIES and parts[3]:
            return ParsedSemanticAddress(
                raw=address,
                kind="node_element",
                node_id=parts[1],
                property_name=parts[2],
                concept_id=parts[3],
            )
        raise InvalidSemanticAddressError(address, "invalid node semantic address")

    if address.startswith("edge:"):
        parts = address.split(":")
        if len(parts) == 2 and parts[1]:
            return ParsedSemanticAddress(raw=address, kind="edge", edge_id=parts[1])
        if len(parts) == 3 and parts[1] and parts[2] == "condition":
            return ParsedSemanticAddress(
                raw=address,
                kind="edge_slot",
                edge_id=parts[1],
                property_name="condition",
            )
        raise InvalidSemanticAddressError(address, "invalid edge semantic address")

    if ":" in address:
        raise InvalidSemanticAddressError(
            address, "bare concept semantic addresses must not contain ':'"
        )
    return ParsedSemanticAddress(raw=address, kind="concept", concept_id=address)


def _as_graph(
    knowledge: StakeholderKnowledge | StakeholderKnowledgeGraph,
) -> StakeholderKnowledgeGraph:
    from .knowledge import StakeholderKnowledge as Knowledge
    from .knowledge import StakeholderKnowledgeGraph as KnowledgeGraph

    if isinstance(knowledge, Knowledge):
        return knowledge.graph
    if isinstance(knowledge, KnowledgeGraph):
        return knowledge
    raise TypeError(
        "knowledge must be StakeholderKnowledge or StakeholderKnowledgeGraph"
    )


def _unknown(address: str, detail: str) -> UnknownSemanticAddressError:
    return UnknownSemanticAddressError(address, detail)


def resolve_semantic_address(
    knowledge: StakeholderKnowledge | StakeholderKnowledgeGraph,
    address: str,
) -> ResolvedSemanticAddress:
    """Resolve one local semantic address or raise a precise address error."""
    graph = _as_graph(knowledge)
    parsed = parse_semantic_address(address)

    if parsed.kind == "concept":
        assert parsed.concept_id is not None
        concept = graph.concepts.get(parsed.concept_id)
        if concept is None:
            raise _unknown(address, "unknown local concept")
        return ResolvedSemanticAddress(
            address=address,
            kind="concept",
            concept_id=parsed.concept_id,
            concept=concept,
            value=concept,
        )

    if parsed.kind in ("node", "node_slot", "node_element"):
        assert parsed.node_id is not None
        node = graph.nodes.get(parsed.node_id)
        if node is None:
            raise _unknown(address, "unknown local node")
        if parsed.kind == "node":
            return ResolvedSemanticAddress(
                address=address,
                kind="node",
                node_id=parsed.node_id,
                node=node,
                value=node,
            )
        assert parsed.property_name is not None
        value = node.slot_value(parsed.property_name)
        if parsed.kind == "node_slot":
            return ResolvedSemanticAddress(
                address=address,
                kind="node_slot",
                node_id=parsed.node_id,
                property_name=parsed.property_name,
                node=node,
                value=value,
            )
        assert parsed.concept_id is not None
        for ref in node.refs(parsed.property_name):
            if ref.concept_id == parsed.concept_id:
                return ResolvedSemanticAddress(
                    address=address,
                    kind="node_element",
                    node_id=parsed.node_id,
                    property_name=parsed.property_name,
                    concept_id=parsed.concept_id,
                    node=node,
                    ref=ref,
                    value=ref,
                )
        raise _unknown(address, "unknown local node list element")

    assert parsed.edge_id is not None
    edge = graph.edges.get(parsed.edge_id)
    if edge is None:
        raise _unknown(address, "unknown local edge")
    if parsed.kind == "edge":
        return ResolvedSemanticAddress(
            address=address,
            kind="edge",
            edge_id=parsed.edge_id,
            edge=edge,
            value=edge,
        )
    return ResolvedSemanticAddress(
        address=address,
        kind="edge_slot",
        edge_id=parsed.edge_id,
        property_name="condition",
        edge=edge,
        value=edge.condition,
    )


def try_resolve_semantic_address(
    knowledge: StakeholderKnowledge | StakeholderKnowledgeGraph,
    address: str,
) -> ResolvedSemanticAddress | None:
    """Return ``None`` instead of raising for invalid or unknown addresses."""
    try:
        return resolve_semantic_address(knowledge, address)
    except SemanticAddressError:
        return None


__all__ = [
    "AddressKind",
    "InvalidSemanticAddressError",
    "NodeAddressProperty",
    "ParsedSemanticAddress",
    "ResolvedSemanticAddress",
    "SemanticAddressError",
    "UnknownSemanticAddressError",
    "parse_semantic_address",
    "resolve_semantic_address",
    "try_resolve_semantic_address",
]
