"""Pure AgentGraph-to-TruthGraph evaluation facade."""

from __future__ import annotations

from dataclasses import asdict

from business_interview.comparison import (
    align_agent_to_truth,
    business_graph_projection,
    compare_aligned_graphs,
    reconstruction_complete,
)
from business_interview.models import (
    AbsentType,
    AgentGraph,
    BusinessProcessGraph,
    ConceptRef,
    DontKnowType,
    EvidenceRef,
    InterviewEvaluationContext,
)

from .coverage import KnowledgeCoverageView, evaluate_knowledge_coverage
from .result import GraphEvaluation, InterviewEvaluation, PrimaryEvaluation


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


_NODE_PROPS = ("activity", "actor", "system", "reads", "writes", "rationale")


def _evidence_metrics(
    context: InterviewEvaluationContext,
    agent: AgentGraph,
) -> tuple[int, int, float, float, float]:
    """Return source-compatible evidence counts and coverage values.

    The validation deliberately visits each reference at the same points as
    the source evaluator.  In particular, repeated EvidenceRef occurrences
    are not deduplicated and a missing observation increments both invalid
    counters for each validation visit.
    """
    invalid = invalid_observation = 0
    ref_total = ref_hit = 0
    node_total = node_hit = 0
    edge_total = edge_hit = 0
    observation_text = {
        observation.id: observation.text for observation in context.observations
    }

    def span_ok(evidence: EvidenceRef) -> bool:
        nonlocal invalid, invalid_observation
        text = observation_text.get(evidence.observation_id)
        if text is None:
            invalid += 1
            invalid_observation += 1
            return False
        if evidence.quote and evidence.resolve_span(text) is None:
            invalid += 1
            return False
        return True

    def all_ok(evidence: list[EvidenceRef]) -> bool:
        ok = True
        for item in evidence:
            if not span_ok(item):
                ok = False
        return ok

    for node in agent.nodes.values():
        refs: list[ConceptRef] = []
        markers: list[EvidenceRef] = []
        for prop in _NODE_PROPS:
            refs.extend(node.refs(prop))
            slot = node.slot_value(prop)
            if isinstance(slot, (AbsentType, DontKnowType)):
                markers.extend(slot.evidence)
        node_total += 1
        if any(
            ref.asserted and any(span_ok(item) for item in ref.evidence) for ref in refs
        ) or any(span_ok(item) for item in markers):
            node_hit += 1
        for ref in refs:
            if not ref.asserted:
                continue
            ref_total += 1
            if ref.evidence and all_ok(ref.evidence):
                ref_hit += 1

    for edge in agent.edges.values():
        edge_total += 1
        if edge.evidence and all_ok(edge.evidence):
            edge_hit += 1

    return (
        invalid,
        invalid_observation,
        node_hit / node_total if node_total else 1.0,
        ref_hit / ref_total if ref_total else 1.0,
        edge_hit / edge_total if edge_total else 1.0,
    )


def _referenced_observations(agent: AgentGraph) -> set[str]:
    """Return observation IDs in the source evaluator's reference surface."""
    ids: set[str] = set()
    for node in agent.nodes.values():
        for prop in _NODE_PROPS:
            for ref in node.refs(prop):
                ids.update(item.observation_id for item in ref.evidence)
            slot = node.slot_value(prop)
            if isinstance(slot, (AbsentType, DontKnowType)):
                ids.update(item.observation_id for item in slot.evidence)
    for edge in agent.edges.values():
        ids.update(item.observation_id for item in edge.evidence)
        # The source tracks evidence on a value-bearing condition reference.
        # Condition marker evidence is outside its orphan-reference surface.
        if isinstance(edge.condition, ConceptRef):
            ids.update(item.observation_id for item in edge.condition.evidence)
    return ids


def _observation_provenance(
    context: InterviewEvaluationContext,
) -> tuple[set[str], int]:
    """Return authentic observation IDs and per-record invalid-source count."""
    authentic_ids: set[str] = set()
    invalid_source = 0
    for observation in context.observations:
        message = context.messages_by_turn.get(observation.turn)
        if (
            observation.turn >= 0
            and message is not None
            and message.role == "user"
            and (message.content or "") == (observation.text or "")
        ):
            authentic_ids.add(observation.id)
        else:
            invalid_source += 1
    return authentic_ids, invalid_source


def evaluate_interview(
    agent: AgentGraph,
    truth: BusinessProcessGraph,
    context: InterviewEvaluationContext,
    *,
    terminology_terms: dict[str, list[str]] | None = None,
) -> InterviewEvaluation:
    """Evaluate graph, evidence provenance, and protocol completion.

    Unlike the graph-only ``evaluate_graph`` facade, this API requires an
    explicit tau2-free context containing raw observation text, the sparse raw
    message ledger, and the completion state.  It never derives provenance
    from Agent-visible observation markers and it does not accept stakeholder
    knowledge.
    """
    graph = evaluate_graph(
        agent,
        truth,
        terminology_terms=terminology_terms,
    )
    authentic_ids, invalid_source = _observation_provenance(context)
    referenced = _referenced_observations(agent)
    orphan_count = sum(
        1 for observation in context.observations if observation.id not in referenced
    )
    (
        invalid_refs,
        invalid_observation_refs,
        node_cov,
        ref_cov,
        edge_cov,
    ) = _evidence_metrics(context, agent)
    provenance_pass = bool(
        invalid_refs == 0 and invalid_observation_refs == 0 and invalid_source == 0
    )
    evidence_pass = bool(
        provenance_pass and node_cov == 1.0 and ref_cov == 1.0 and edge_cov == 1.0
    )

    return InterviewEvaluation(
        protocol_completed=context.protocol_completed,
        graph_created=graph.graph_created,
        graph_valid=graph.graph_valid,
        node_recall=graph.node_recall,
        node_precision=graph.node_precision,
        edge_recall=graph.edge_recall,
        edge_precision=graph.edge_precision,
        start_correct=graph.start_correct,
        end_recall=graph.end_recall,
        end_precision=graph.end_precision,
        activity_correctness=graph.activity_correctness,
        actor_correctness=graph.actor_correctness,
        system_correctness=graph.system_correctness,
        read_correctness=graph.read_correctness,
        write_correctness=graph.write_correctness,
        rationale_correctness=graph.rationale_correctness,
        condition_correctness=graph.condition_correctness,
        concept_correctness=graph.concept_correctness,
        concept_recall=graph.concept_recall,
        concept_precision=graph.concept_precision,
        unsupported_ref_count=graph.unsupported_ref_count,
        fabricated_node_count=graph.fabricated_node_count,
        fabricated_edge_count=graph.fabricated_edge_count,
        glossary_complete=graph.glossary_complete,
        node_evidence_coverage=node_cov,
        ref_evidence_coverage=ref_cov,
        edge_evidence_coverage=edge_cov,
        invalid_evidence_ref_count=invalid_refs,
        ambiguous_evidence_ref_count=0,
        marker_evidence_errors_surrogate=0,
        invalid_observation_reference_count=invalid_observation_refs,
        authentic_observation_count=len(authentic_ids),
        invalid_observation_source_count=invalid_source,
        orphan_observation_count=orphan_count,
        provenance_authenticity_pass=provenance_pass,
        evidence_pass=evidence_pass,
        reconstruction_pass=graph.reconstruction_pass,
        structural_pass=graph.structural_pass,
        protocol_pass=context.protocol_completed,
        quality_pass=graph.quality_pass,
    )


def evaluate_primary(
    agent: AgentGraph,
    truth: BusinessProcessGraph,
    context: InterviewEvaluationContext,
    knowledge: KnowledgeCoverageView,
    *,
    terminology_terms: dict[str, list[str]] | None = None,
) -> PrimaryEvaluation:
    """Return the complete 41-field primary result.

    The first 40 fields are produced only by ``evaluate_interview``.  This
    facade adds the independent, informational knowledge coverage value and
    does not feed it into any graph, evidence, or protocol pass predicate.
    """
    interview = evaluate_interview(
        agent,
        truth,
        context,
        terminology_terms=terminology_terms,
    )
    return PrimaryEvaluation(
        **asdict(interview),
        knowledge_coverage=evaluate_knowledge_coverage(truth, knowledge),
    )


__all__ = ["evaluate_graph", "evaluate_interview", "evaluate_primary"]
