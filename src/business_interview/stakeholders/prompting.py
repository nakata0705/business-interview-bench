"""Short private prompt rendering for a stakeholder knowledge world."""

from __future__ import annotations

from html import escape
from typing import Any

from .knowledge import (
    KnowledgeConceptRef,
    StakeholderKnowledge,
    StakeholderKnowledgeGraph,
    is_dont_know,
)
from .response import canonical_semantic_mode

_NODE_PROPERTIES = ("activity", "actor", "system", "rationale", "reads", "writes")


def _graph(
    knowledge: StakeholderKnowledge | StakeholderKnowledgeGraph,
) -> StakeholderKnowledgeGraph:
    if isinstance(knowledge, StakeholderKnowledge):
        return knowledge.graph
    if isinstance(knowledge, StakeholderKnowledgeGraph):
        return knowledge
    raise TypeError(
        "knowledge must be StakeholderKnowledge or StakeholderKnowledgeGraph"
    )


def _text(value: Any) -> str:
    return escape(str(value), quote=True)


def _slot_state(value: Any) -> str:
    if is_dont_know(value):
        return 'state="dont_know"'
    if value is None:
        return 'state="absent"'
    if isinstance(value, KnowledgeConceptRef):
        return f'state="value" concept_id="{_text(value.concept_id)}"'
    if isinstance(value, (tuple, list)):
        concept_ids = [
            ref.concept_id for ref in value if isinstance(ref, KnowledgeConceptRef)
        ]
        return f'state="value" concept_ids="{_text(",".join(concept_ids))}"'
    return f'state="value" value="{_text(value)}"'


def _render_node(graph: StakeholderKnowledgeGraph, node_id: str) -> str:
    node = graph.nodes[node_id]
    role = node.structural_role or "business"
    attributes = [f'role="{_text(role)}"']
    if node.is_structural:
        attributes.append('structural="true"')
        return f"<position {' '.join(attributes)}/>"

    node_semantic_id = f"node:{node_id}"
    attributes = [
        f'semantic_id="{_text(node_semantic_id)}"',
        f'required_mode="{canonical_semantic_mode(graph, node_semantic_id)}"',
        *attributes,
    ]
    lines = [f"<position {' '.join(attributes)}>"]
    for property_name in _NODE_PROPERTIES:
        semantic_id = f"node:{node_id}:{property_name}"
        value = node.slot_value(property_name)
        lines.append(
            f'  <slot semantic_id="{_text(semantic_id)}" '
            f'required_mode="{canonical_semantic_mode(graph, semantic_id)}" '
            f"{_slot_state(value)}/>"
        )
        if property_name in ("reads", "writes") and isinstance(value, (tuple, list)):
            for ref in value:
                if isinstance(ref, KnowledgeConceptRef):
                    element_id = f"{semantic_id}:{ref.concept_id}"
                    lines.append(
                        f'  <element semantic_id="{_text(element_id)}" '
                        f'concept_id="{_text(ref.concept_id)}" '
                        f'required_mode="{canonical_semantic_mode(graph, element_id)}" '
                        'state="value"/>'
                    )
    lines.append("</position>")
    return "\n".join(lines)


def _endpoint(graph: StakeholderKnowledgeGraph, node_id: str) -> str:
    if node_id == graph.source_node_id:
        return "source"
    if node_id == graph.sink_node_id:
        return "sink"
    return f"node:{node_id}"


def _render_edge(graph: StakeholderKnowledgeGraph, edge_id: str) -> str:
    edge = graph.edges[edge_id]
    if edge.is_structural:
        return (
            f'<relation from="{_text(_endpoint(graph, edge.from_node))}" '
            f'to="{_text(_endpoint(graph, edge.to_node))}" '
            f'kind="{_text(edge.edge_kind)}" structural="true"/>'
        )
    semantic_id = f"edge:{edge_id}"
    condition_id = f"{semantic_id}:condition"
    lines = [
        f'<relation semantic_id="{_text(semantic_id)}" '
        f'required_mode="{canonical_semantic_mode(graph, semantic_id)}" '
        f'from="{_text(_endpoint(graph, edge.from_node))}" '
        f'to="{_text(_endpoint(graph, edge.to_node))}" '
        f'kind="{_text(edge.edge_kind)}">',
        f'  <slot semantic_id="{_text(condition_id)}" '
        f'required_mode="{canonical_semantic_mode(graph, condition_id)}" '
        f"{_slot_state(edge.condition)}/>",
        "</relation>",
    ]
    return "\n".join(lines)


def _render_concept(graph: StakeholderKnowledgeGraph, concept_id: str) -> str:
    concept = graph.concepts[concept_id]
    if is_dont_know(concept.description):
        description = 'description_state="dont_know"'
    else:
        description = f'description="{_text(concept.description)}"'
    if is_dont_know(concept.terms):
        terms = 'terms_state="dont_know"'
    else:
        terms_value = concept.terms
        if not isinstance(terms_value, tuple):
            raise TypeError("invalid knowledge concept terms")
        terms = f'terms="{_text(",".join(terms_value))}"'
    return (
        f'<concept semantic_id="{_text(concept_id)}" '
        f'required_mode="{canonical_semantic_mode(graph, concept_id)}" '
        f"{description} {terms}/>"
    )


def render_knowledge_prompt(
    knowledge: StakeholderKnowledge | StakeholderKnowledgeGraph,
) -> str:
    """Render only stakeholder-local knowledge for private model context.

    The renderer deliberately ignores Truth mappings, graph names, and all
    evaluator metadata.  Values and concepts therefore come only from the
    supplied stakeholder world model.
    """
    graph = _graph(knowledge)
    positions = "\n".join(
        _render_node(graph, node_id) for node_id in sorted(graph.nodes)
    )
    relations = "\n".join(
        _render_edge(graph, edge_id) for edge_id in sorted(graph.edges)
    )
    concepts = "\n".join(
        _render_concept(graph, concept_id) for concept_id in sorted(graph.concepts)
    )
    return (
        "You are a stakeholder. Use only the private knowledge below. "
        "Local semantic IDs are private annotation handles and must never "
        "appear in the public message. Do not invent unknown values. "
        "Every selectable semantic_id includes its canonical required_mode; "
        "copy that mode exactly when planning an assertion.\n"
        "<private_knowledge>\n"
        "<positions>\n"
        f"{positions}\n"
        "</positions>\n"
        "<relations>\n"
        f"{relations}\n"
        "</relations>\n"
        "<concepts>\n"
        f"{concepts}\n"
        "</concepts>\n"
        "</private_knowledge>"
    )


__all__ = ["render_knowledge_prompt"]
