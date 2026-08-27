"""Pure AgentGraph-to-TruthGraph evaluation facade."""

from __future__ import annotations

from business_interview.comparison import (
    align_agent_to_truth,
    business_graph_projection,
    compare_aligned_graphs,
    reconstruction_complete,
)
from business_interview.models import AgentGraph, BusinessProcessGraph

from .result import GraphEvaluation


def evaluate_graph(
    agent: AgentGraph,
    truth: BusinessProcessGraph,
    *,
    terminology_terms: dict[str, list[str]] | None = None,
) -> GraphEvaluation:
    """Evaluate an Agent graph against a canonical Truth graph.

    The facade only orchestrates the existing deterministic comparison core:
    canonical Truth is projected to business elements, concepts/nodes/edges
    are aligned, and the aligned metrics are assembled into a small result.
    The input graphs are read-only from the evaluator's perspective.
    """
    truth_view = business_graph_projection(truth)
    alignment = align_agent_to_truth(
        agent,
        truth_view,
        terminology_terms=terminology_terms,
    )
    comparison = compare_aligned_graphs(agent, truth_view, alignment)

    # The source currently exposes the same graph-completeness predicate under
    # all three pass names.  Keep that relationship explicit rather than
    # deriving pass values from a fixture-specific result.
    structural_pass = reconstruction_complete(comparison)
    reconstruction_pass = structural_pass
    quality_pass = structural_pass

    return GraphEvaluation(
        graph_created=comparison.graph_created,
        graph_valid=comparison.graph_valid,
        node_recall=comparison.node_recall,
        node_precision=comparison.node_precision,
        edge_recall=comparison.edge_recall,
        edge_precision=comparison.edge_precision,
        start_correct=comparison.start_correct,
        end_recall=comparison.end_recall,
        end_precision=comparison.end_precision,
        activity_correctness=comparison.activity_correctness,
        actor_correctness=comparison.actor_correctness,
        system_correctness=comparison.system_correctness,
        read_correctness=comparison.read_correctness,
        write_correctness=comparison.write_correctness,
        rationale_correctness=comparison.rationale_correctness,
        condition_correctness=comparison.condition_correctness,
        concept_correctness=comparison.concept_correctness,
        concept_recall=comparison.concept_recall,
        concept_precision=comparison.concept_precision,
        unsupported_ref_count=comparison.unsupported_ref_count,
        fabricated_node_count=comparison.fabricated_node_count,
        fabricated_edge_count=comparison.fabricated_edge_count,
        glossary_complete=comparison.glossary_complete,
        structural_pass=structural_pass,
        reconstruction_pass=reconstruction_pass,
        quality_pass=quality_pass,
    )


__all__ = ["evaluate_graph"]
