"""Tau2-free deterministic Agent-to-Truth comparison core."""

# The workspace-level auxiliary Pyright runner can miss freshly added sibling
# modules; project-level ``uv run pyright`` remains the authoritative check.
# pyright: reportMissingImports=false

from .alignment import GraphAlignment, align_agent_to_truth
from .assignment import assignment_score, bipartite_components, max_weight_assignment
from .concepts import (
    CONCEPT_MATCH_THRESHOLD,
    ConceptAlignment,
    align_concepts,
    concept_similarity,
    dice_similarity,
    normalize_text,
    tokenize,
)
from .projection import BusinessGraphView, business_graph_projection
from .scoring import (
    AlignedGraphComparison,
    compare_aligned_graphs,
    score_list_slot,
    score_scalar_slot,
)

__all__ = [
    "CONCEPT_MATCH_THRESHOLD",
    "AlignedGraphComparison",
    "BusinessGraphView",
    "assignment_score",
    "bipartite_components",
    "ConceptAlignment",
    "GraphAlignment",
    "align_agent_to_truth",
    "align_concepts",
    "business_graph_projection",
    "compare_aligned_graphs",
    "concept_similarity",
    "dice_similarity",
    "max_weight_assignment",
    "normalize_text",
    "score_list_slot",
    "score_scalar_slot",
    "tokenize",
]
