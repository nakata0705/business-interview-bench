"""Result value object for the standalone graph evaluator."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GraphEvaluation:
    """The 26 metrics computable from an AgentGraph and a TruthGraph.

    The result deliberately contains only graph/content comparison metrics and
    the three graph-derived pass values.  Observation, protocol, provenance,
    stakeholder-knowledge, and diagnostic values require a different input
    contract and are not represented here.
    """

    graph_created: bool
    graph_valid: bool
    node_recall: float
    node_precision: float
    edge_recall: float
    edge_precision: float
    start_correct: bool
    end_recall: float
    end_precision: float
    activity_correctness: float
    actor_correctness: float
    system_correctness: float
    read_correctness: float
    write_correctness: float
    rationale_correctness: float
    condition_correctness: float
    concept_correctness: float
    concept_recall: float
    concept_precision: float
    unsupported_ref_count: int
    fabricated_node_count: int
    fabricated_edge_count: int
    glossary_complete: bool
    structural_pass: bool
    reconstruction_pass: bool
    quality_pass: bool


__all__ = ["GraphEvaluation"]
