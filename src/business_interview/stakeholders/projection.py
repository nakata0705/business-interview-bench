"""Pure Truth-to-stakeholder knowledge projection.

This module is the Phase 10 domain boundary.  It applies a
:class:`StakeholderProfile` to a canonical Truth graph, using a local RNG for
forgetting and bounded rejection sampling for unsafe topology samples.  It
never renders prompts, calls an LLM, mutates a Truth graph, or owns runtime
conversation state.
"""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from business_interview.evaluation.coverage import (
    CoverageEdge,
    CoverageListSlot,
    CoverageNode,
    CoverageScalarState,
    KnowledgeCoverageView,
)
from business_interview.models import (
    STRUCTURAL_SINK_ID,
    STRUCTURAL_SOURCE_ID,
    BusinessProcessGraph,
    ConceptRef,
    TruthEdge,
    business_edge_ids,
    business_node_ids,
    canonical_structure_errors,
    edge_is_structural,
)

from .config import StakeholderProfile
from .knowledge import (
    DONT_KNOW,
    KnowledgeConceptRef,
    KnowledgeListSlot,
    KnowledgeSlot,
    ShortcutProvenance,
    StakeholderEdge,
    StakeholderKnowledge,
    StakeholderKnowledgeConcept,
    StakeholderKnowledgeGraph,
    StakeholderNode,
    is_dont_know,
    validate_stakeholder_knowledge,
)

_NODE_PROPERTIES = (
    "activity",
    "actor",
    "system",
    "reads",
    "writes",
    "rationale",
)


class _RandomSource(Protocol):
    def random(self) -> float: ...


class KnowledgeProjectionError(ValueError):
    """Raised when bounded forgetting retries cannot produce valid knowledge."""

    def __init__(
        self,
        message: str,
        *,
        attempts: int,
        reasons: Sequence[str],
        config: Mapping[str, Any],
    ) -> None:
        self.attempts = attempts
        self.reasons = tuple(reasons)
        self.config = dict(config)
        super().__init__(message)


class _ProjectionRejected(Exception):
    """Internal reason for rejecting one forgetting sample."""


def _truth_reference_errors(truth: BusinessProcessGraph) -> list[str]:
    errors: list[str] = []
    for node_id, node in truth.nodes.items():
        for property_name in _NODE_PROPERTIES:
            for ref in node.refs(property_name):
                if ref.concept_id not in truth.concepts:
                    errors.append(
                        f"node {node_id}: {property_name} references unknown "
                        f"Truth concept {ref.concept_id!r}"
                    )
    for edge_id, edge in truth.edges.items():
        if (
            isinstance(edge.condition, ConceptRef)
            and edge.condition.concept_id not in truth.concepts
        ):
            errors.append(
                f"edge {edge_id}: condition references unknown Truth concept "
                f"{edge.condition.concept_id!r}"
            )
    return errors


def _validate_truth(truth: BusinessProcessGraph) -> None:
    if not isinstance(truth, BusinessProcessGraph):
        raise TypeError("truth must be a BusinessProcessGraph")
    errors = canonical_structure_errors(truth)
    errors.extend(_truth_reference_errors(truth))
    if errors:
        raise ValueError("Truth graph is not canonical:\n- " + "\n- ".join(errors))


def _truth_refs(value: object) -> tuple[ConceptRef, ...]:
    if isinstance(value, ConceptRef):
        return (value,)
    if isinstance(value, list):
        return tuple(sorted(value, key=lambda ref: ref.concept_id))
    return ()


def _opaque_ids(
    truth_ids: Sequence[str],
    prefix: str,
    *,
    forbidden_ids: set[str] | frozenset[str] = frozenset(),
) -> dict[str, str]:
    """Assign index-only local IDs in sorted semantic order.

    The generated text contains no Truth ID, label, term, or description.  The
    sorted order only makes assignment reproducible; the private mapping in
    the result retains the actual Truth correspondence.  Skipping a reserved
    index avoids accidental local/Truth ID collisions without encoding Truth
    text in a local identifier.
    """
    local_ids: dict[str, str] = {}
    ordinal = 1
    for truth_id in sorted(truth_ids):
        local_id = f"{prefix}{ordinal:03d}"
        while local_id in forbidden_ids:
            ordinal += 1
            local_id = f"{prefix}{ordinal:03d}"
        local_ids[truth_id] = local_id
        ordinal += 1
    return local_ids


def _slot_to_local(
    value: object,
    *,
    known: bool,
    truth_to_local: Mapping[str, str],
) -> KnowledgeSlot:
    if not known:
        return DONT_KNOW
    if value is None:
        return None
    if not isinstance(value, ConceptRef):
        raise _ProjectionRejected("Truth slot has an unsupported value")
    try:
        return KnowledgeConceptRef(concept_id=truth_to_local[value.concept_id])
    except KeyError as exc:
        raise _ProjectionRejected(
            f"known Truth concept was not projected: {value.concept_id!r}"
        ) from exc


def _list_slot_to_local(
    value: object,
    *,
    known: bool,
    truth_to_local: Mapping[str, str],
) -> KnowledgeListSlot:
    if not known:
        return DONT_KNOW
    refs = _truth_refs(value)
    if not refs:
        return None
    try:
        return tuple(
            KnowledgeConceptRef(concept_id=truth_to_local[ref.concept_id])
            for ref in refs
        )
    except KeyError as exc:
        raise _ProjectionRejected(
            f"known Truth concept was not projected: {exc.args[0]!r}"
        ) from exc


def _copy_truth_edge(edge: TruthEdge) -> TruthEdge:
    return edge.model_copy(deep=True)


def _contract_forgotten_nodes(
    truth: BusinessProcessGraph,
    nodes: set[str],
    edges: dict[str, TruthEdge],
    forgotten_nodes: set[str],
    known_condition_edges: set[str],
    *,
    allow_shortcut: bool,
) -> tuple[set[str], dict[str, TruthEdge], set[str]]:
    """Contract forgotten nodes only when their current path is safely serial."""
    if forgotten_nodes and not allow_shortcut:
        raise _ProjectionRejected("shortcut contraction is disabled")

    source = truth.source_node_id
    sink = truth.sink_node_id
    remaining_nodes = set(nodes)
    remaining_edges = dict(edges)
    known_conditions = set(known_condition_edges)
    shortcut_ordinal = 1

    for node_id in sorted(forgotten_nodes):
        if node_id not in remaining_nodes:
            continue
        if node_id in {source, sink}:
            raise _ProjectionRejected(
                "structural SOURCE/SINK was selected for forgetting"
            )

        incoming = sorted(
            (edge for edge in remaining_edges.values() if edge.to_node == node_id),
            key=lambda edge: edge.id,
        )
        outgoing = sorted(
            (edge for edge in remaining_edges.values() if edge.from_node == node_id),
            key=lambda edge: edge.id,
        )
        if len(incoming) != 1 or len(outgoing) != 1:
            raise _ProjectionRejected(
                f"node {node_id!r} is not an eligible serial node "
                f"(indegree={len(incoming)}, outdegree={len(outgoing)})"
            )

        left, right = incoming[0], outgoing[0]
        if left.condition is not None or right.condition is not None:
            raise _ProjectionRejected(
                f"contraction of {node_id!r} has conditioned incident path"
            )
        predecessor, successor = left.from_node, right.to_node
        if predecessor == successor:
            raise _ProjectionRejected(
                f"contraction of {node_id!r} would create a self-loop"
            )
        if any(
            edge.id not in {left.id, right.id}
            and edge.from_node == predecessor
            and edge.to_node == successor
            for edge in remaining_edges.values()
        ):
            raise _ProjectionRejected(
                f"contraction of {node_id!r} would create parallel edges"
            )

        derived_from_edges = list(left.derived_from_edges) or [left.id]
        derived_from_edges.extend(list(right.derived_from_edges) or [right.id])
        contracted_nodes = list(left.contracted_nodes)
        contracted_nodes.append(node_id)
        contracted_nodes.extend(right.contracted_nodes)

        new_id = f"__stakeholder_shortcut__{shortcut_ordinal:03d}"
        while new_id in remaining_edges:
            shortcut_ordinal += 1
            new_id = f"__stakeholder_shortcut__{shortcut_ordinal:03d}"
        shortcut_ordinal += 1

        structural_boundary = predecessor == source or successor == sink
        remaining_edges[new_id] = TruthEdge(
            id=new_id,
            from_node=predecessor,
            to_node=successor,
            condition=None,
            edge_kind=("structural_boundary" if structural_boundary else "shortcut"),
            structural_only=structural_boundary,
            protected=structural_boundary,
            is_shortcut=True,
            contracted_nodes=contracted_nodes,
            derived_from_edges=derived_from_edges,
        )
        remaining_edges.pop(left.id)
        remaining_edges.pop(right.id)
        remaining_nodes.remove(node_id)
        known_conditions.discard(left.id)
        known_conditions.discard(right.id)
        # A safe shortcut has no composed condition, but source semantics allow
        # property forgetting to mask this derived slot after contraction.
        known_conditions.add(new_id)

    return remaining_nodes, remaining_edges, known_conditions


def _sample_projection(
    truth: BusinessProcessGraph,
    profile: StakeholderProfile,
    rng: _RandomSource,
) -> StakeholderKnowledge:
    all_business_nodes = set(business_node_ids(truth))
    all_business_edges = set(business_edge_ids(truth))
    visible_nodes = all_business_nodes & set(profile.visible_node_ids)
    visible_edges = all_business_edges & set(profile.visible_edge_ids)

    config = profile.forgetting
    forgotten_nodes = all_business_nodes - visible_nodes
    if config.effective_node_probability > 0.0:
        for node_id in sorted(visible_nodes):
            if rng.random() < config.effective_node_probability:
                forgotten_nodes.add(node_id)

    forgotten_edges = all_business_edges - visible_edges
    if config.effective_edge_probability > 0.0:
        for edge_id in sorted(visible_edges):
            if rng.random() < config.effective_edge_probability:
                forgotten_edges.add(edge_id)

    # Keep all structural boundaries in the working topology.  Business edge
    # visibility is applied before node contraction so missing incident edges
    # reject the sample instead of being silently invented.
    working_nodes = all_business_nodes | {truth.source_node_id, truth.sink_node_id}
    working_edges: dict[str, TruthEdge] = {}
    for edge_id, edge in truth.edges.items():
        if edge_is_structural(edge) or (
            edge_id in visible_edges and edge_id not in forgotten_edges
        ):
            working_edges[edge_id] = _copy_truth_edge(edge)

    known_condition_edges = {
        edge_id
        for edge_id, edge in working_edges.items()
        if not edge_is_structural(edge)
        and edge_id in visible_edges
        and "condition" in profile.edge_properties_for(edge_id)
    }
    remaining_nodes, remaining_edges, known_condition_edges = _contract_forgotten_nodes(
        truth,
        working_nodes,
        working_edges,
        forgotten_nodes,
        known_condition_edges,
        allow_shortcut=config.allow_shortcut_contraction,
    )

    if config.property_forget_probability > 0.0:
        for edge_id in sorted(known_condition_edges):
            edge = remaining_edges.get(edge_id)
            if edge is not None and not edge_is_structural(edge):
                if rng.random() < config.property_forget_probability:
                    known_condition_edges.discard(edge_id)

    final_business_nodes = remaining_nodes - {
        truth.source_node_id,
        truth.sink_node_id,
    }
    if not final_business_nodes:
        raise _ProjectionRejected("forgetting removed every business node")

    known_node_properties: dict[str, set[str]] = {}
    for node_id in sorted(final_business_nodes):
        configured = profile.node_properties_for(node_id)
        known: set[str] = set()
        for property_name in _NODE_PROPERTIES:
            if property_name not in configured:
                continue
            if (
                config.property_forget_probability == 0.0
                or rng.random() >= config.property_forget_probability
            ):
                known.add(property_name)
        known_node_properties[node_id] = known

    all_truth_ids = set(truth.nodes) | set(truth.edges) | set(truth.concepts)
    final_node_ids = sorted(final_business_nodes)
    node_to_local = _opaque_ids(
        final_node_ids,
        "skn_",
        forbidden_ids=all_truth_ids,
    )
    node_to_local[truth.source_node_id] = STRUCTURAL_SOURCE_ID
    node_to_local[truth.sink_node_id] = STRUCTURAL_SINK_ID

    final_edge_ids = sorted(remaining_edges)
    edge_to_local = _opaque_ids(
        final_edge_ids,
        "ske_",
        forbidden_ids=all_truth_ids,
    )

    referenced_truth_concepts: set[str] = set()
    for node_id in final_node_ids:
        truth_node = truth.nodes[node_id]
        for property_name in _NODE_PROPERTIES:
            if property_name in known_node_properties[node_id]:
                referenced_truth_concepts.update(
                    ref.concept_id
                    for ref in _truth_refs(truth_node.slot_value(property_name))
                )
    for edge_id in final_edge_ids:
        edge = remaining_edges[edge_id]
        if (
            not edge_is_structural(edge)
            and not edge.is_shortcut
            and edge_id in known_condition_edges
        ):
            referenced_truth_concepts.update(
                ref.concept_id for ref in _truth_refs(edge.condition)
            )

    truth_to_local = _opaque_ids(
        sorted(referenced_truth_concepts),
        "skc_",
        forbidden_ids=all_truth_ids,
    )

    def local_scalar(value: object, property_name: str, node_id: str) -> KnowledgeSlot:
        return _slot_to_local(
            value,
            known=property_name in known_node_properties[node_id],
            truth_to_local=truth_to_local,
        )

    local_nodes: dict[str, StakeholderNode] = {
        STRUCTURAL_SOURCE_ID: StakeholderNode(
            id=STRUCTURAL_SOURCE_ID,
            structural=True,
            structural_role="source",
            protected=True,
        ),
        STRUCTURAL_SINK_ID: StakeholderNode(
            id=STRUCTURAL_SINK_ID,
            structural=True,
            structural_role="sink",
            protected=True,
        ),
    }
    for node_id in final_node_ids:
        truth_node = truth.nodes[node_id]
        properties = known_node_properties[node_id]
        local_nodes[node_to_local[node_id]] = StakeholderNode(
            id=node_to_local[node_id],
            activity=local_scalar(truth_node.activity, "activity", node_id),
            actor=local_scalar(truth_node.actor, "actor", node_id),
            system=local_scalar(truth_node.system, "system", node_id),
            reads=_list_slot_to_local(
                truth_node.reads,
                known="reads" in properties,
                truth_to_local=truth_to_local,
            ),
            writes=_list_slot_to_local(
                truth_node.writes,
                known="writes" in properties,
                truth_to_local=truth_to_local,
            ),
            rationale=local_scalar(
                truth_node.necessity_rationale,
                "rationale",
                node_id,
            ),
        )

    local_edges: dict[str, StakeholderEdge] = {}
    shortcut_provenance: dict[str, ShortcutProvenance] = {}
    for edge_id in final_edge_ids:
        truth_edge = remaining_edges[edge_id]
        local_id = edge_to_local[edge_id]
        if edge_is_structural(truth_edge):
            condition: KnowledgeSlot = None
        elif truth_edge.is_shortcut:
            condition = None if edge_id in known_condition_edges else DONT_KNOW
        elif edge_id not in known_condition_edges:
            condition = DONT_KNOW
        else:
            condition = _slot_to_local(
                truth_edge.condition,
                known=True,
                truth_to_local=truth_to_local,
            )
        local_edges[local_id] = StakeholderEdge(
            id=local_id,
            from_node=node_to_local[truth_edge.from_node],
            to_node=node_to_local[truth_edge.to_node],
            condition=condition,
            edge_kind=truth_edge.edge_kind,
            structural_only=truth_edge.structural_only,
            protected=truth_edge.protected,
            is_shortcut=truth_edge.is_shortcut,
            contracted_nodes=tuple(truth_edge.contracted_nodes),
            derived_from_edges=tuple(truth_edge.derived_from_edges),
        )
        if truth_edge.is_shortcut:
            shortcut_provenance[local_id] = ShortcutProvenance(
                is_shortcut=True,
                contracted_nodes=tuple(truth_edge.contracted_nodes),
                derived_from_edges=tuple(truth_edge.derived_from_edges),
            )

    local_concepts: dict[str, StakeholderKnowledgeConcept] = {}
    for truth_id, local_id in sorted(truth_to_local.items()):
        truth_concept = truth.concepts[truth_id]
        override = profile.concept_override_for(truth_id)
        description: object = (
            DONT_KNOW
            if override is not None and not override.description_known
            else truth_concept.description
        )
        if override is not None and not override.terms_known:
            terms: object = DONT_KNOW
        elif override is not None and override.local_terms is not None:
            terms = override.local_terms
        else:
            terms = tuple(sorted(truth_concept.canonical_terms))
        local_concepts[local_id] = StakeholderKnowledgeConcept(
            id=local_id,
            truth_concept_id=truth_id,
            kind=truth_concept.kind,
            description=description,
            terms=terms,
        )

    graph = StakeholderKnowledgeGraph(
        id=truth.id,
        name=truth.name,
        nodes=local_nodes,
        edges=local_edges,
        concepts=local_concepts,
        source_node_id=STRUCTURAL_SOURCE_ID,
        sink_node_id=STRUCTURAL_SINK_ID,
        node_truth_ids={
            local_id: truth_id for truth_id, local_id in node_to_local.items()
        },
        edge_truth_ids={
            edge_to_local[edge_id]: (
                "__shortcut__" if remaining_edges[edge_id].is_shortcut else edge_id
            )
            for edge_id in final_edge_ids
        },
        shortcut_provenance=shortcut_provenance,
    )
    knowledge = StakeholderKnowledge(graph=graph)
    try:
        validate_stakeholder_knowledge(knowledge)
    except ValueError as exc:
        raise _ProjectionRejected(str(exc)) from exc
    return knowledge


def project_knowledge(
    truth: BusinessProcessGraph,
    profile: StakeholderProfile,
    *,
    seed: int | None = None,
    rng: random.Random | None = None,
) -> StakeholderKnowledge:
    """Project canonical Truth into one valid private stakeholder world model.

    ``seed`` creates a private ``random.Random(seed)`` stream and therefore
    never changes module-global random state.  ``seed=None`` uses a private
    ``random.Random(None)`` stream and is intentionally non-reproducible when
    forgetting probabilities are non-zero.  ``rng`` is an optional explicit
    test/integration seam; it cannot be combined with ``seed``.  Retry attempts
    share the same RNG stream and are bounded by ``profile.forgetting``.
    """
    _validate_truth(truth)
    if not isinstance(profile, StakeholderProfile):
        raise TypeError("profile must be a StakeholderProfile")
    if seed is not None and rng is not None:
        raise ValueError("pass either seed or rng, not both")

    generator: _RandomSource = rng if rng is not None else random.Random(seed)
    rng_source = (
        "caller-provided random source"
        if rng is not None
        else ("random.Random(seed)" if seed is not None else "random.Random(None)")
    )
    attempts = profile.forgetting.max_retries
    reasons: list[str] = []
    for _attempt in range(1, attempts + 1):
        try:
            knowledge = _sample_projection(truth, profile, generator)
            result = knowledge.model_copy(
                update={
                    "generation_seed": seed,
                    "generation_rng_source": rng_source,
                }
            )
            validate_stakeholder_knowledge(result)
            return result
        except _ProjectionRejected as exc:
            reasons.append(str(exc))

    reason_summary = "; ".join(dict.fromkeys(reasons[-8:]))
    raise KnowledgeProjectionError(
        "unable to generate a valid stakeholder graph after "
        f"{attempts} forgetting attempts; configuration="
        f"{profile.forgetting.model_dump()}; validation_failures={reason_summary}",
        attempts=attempts,
        reasons=reasons,
        config=profile.forgetting.model_dump(),
    )


def _coverage_scalar(value: object) -> CoverageScalarState:
    return "dont_know" if is_dont_know(value) else "known"


def _coverage_list_slot(
    value: object,
    graph: StakeholderKnowledgeGraph,
) -> CoverageListSlot:
    if is_dont_know(value):
        return CoverageListSlot(state="dont_know")
    if value is None:
        return CoverageListSlot(state="known_absent")
    if not isinstance(value, tuple):
        raise ValueError("projected list slot must be a tuple")
    truth_ids: list[str] = []
    for ref in value:
        concept = graph.concepts.get(ref.concept_id)
        if concept is None:
            raise ValueError(
                f"projected list slot references unknown concept {ref.concept_id!r}"
            )
        truth_ids.append(concept.truth_concept_id)
    return CoverageListSlot(
        state="known_values",
        truth_concept_ids=tuple(sorted(truth_ids)),
    )


def knowledge_coverage_view(
    truth: BusinessProcessGraph,
    knowledge: StakeholderKnowledge,
) -> KnowledgeCoverageView:
    """Derive evaluator coverage solely from private projected knowledge."""
    _validate_truth(truth)
    if not isinstance(knowledge, StakeholderKnowledge):
        raise TypeError("knowledge must be a StakeholderKnowledge")
    validate_stakeholder_knowledge(knowledge)
    graph = knowledge.graph

    truth_to_local_node = {
        truth_id: local_id for local_id, truth_id in graph.node_truth_ids.items()
    }
    coverage_nodes: dict[str, CoverageNode] = {}
    for truth_node_id in business_node_ids(truth):
        local_id = truth_to_local_node.get(truth_node_id)
        if local_id is None:
            continue
        node = graph.nodes.get(local_id)
        if node is None:
            raise ValueError(f"node mapping has no local node: {local_id}")
        coverage_nodes[truth_node_id] = CoverageNode(
            truth_node_id=truth_node_id,
            activity=_coverage_scalar(node.activity),
            actor=_coverage_scalar(node.actor),
            system=_coverage_scalar(node.system),
            reads=_coverage_list_slot(node.reads, graph),
            writes=_coverage_list_slot(node.writes, graph),
            rationale=_coverage_scalar(node.rationale),
        )

    truth_to_local_edge = {
        truth_id: local_id for local_id, truth_id in graph.edge_truth_ids.items()
    }
    coverage_edges: dict[str, CoverageEdge] = {}
    for truth_edge_id in business_edge_ids(truth):
        local_id = truth_to_local_edge.get(truth_edge_id)
        if local_id is None:
            continue
        edge = graph.edges.get(local_id)
        if edge is None:
            raise ValueError(f"edge mapping has no local edge: {local_id}")
        coverage_edges[truth_edge_id] = CoverageEdge(
            truth_edge_id=truth_edge_id,
            condition=_coverage_scalar(edge.condition),
        )

    return KnowledgeCoverageView(
        nodes_by_truth_id=coverage_nodes,
        edges_by_truth_id=coverage_edges,
    )


# Descriptive alias for callers that prefer the derived-view wording.
derive_knowledge_coverage_view = knowledge_coverage_view


__all__ = [
    "KnowledgeProjectionError",
    "derive_knowledge_coverage_view",
    "knowledge_coverage_view",
    "project_knowledge",
]
