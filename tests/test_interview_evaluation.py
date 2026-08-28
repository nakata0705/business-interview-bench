"""Focused Phase 6 observation, evidence, provenance, and protocol tests."""

from __future__ import annotations

import json
from dataclasses import asdict, fields
from pathlib import Path

import pytest

from business_interview.evaluation import InterviewEvaluation, evaluate_interview
from business_interview.models import (
    ABSENT,
    AbsentType,
    AgentConcept,
    AgentEdge,
    AgentGraph,
    AgentNode,
    BusinessProcessGraph,
    ConceptRef,
    EvidenceRef,
    InterviewEvaluationContext,
    LedgerMessage,
    ObservationRecord,
    TruthConcept,
    TruthEdge,
    TruthNode,
    canonicalize_truth_graph,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = PROJECT_ROOT / "tests" / "fixtures" / "seed9004"

INTERVIEW_FIELDS = tuple(field.name for field in fields(InterviewEvaluation))


def _evidence(
    observation_id: str = "obs_1",
    *,
    quote: str | None = "fact",
    occurrence: int = 0,
) -> EvidenceRef:
    return EvidenceRef(
        observation_id=observation_id,
        quote=quote,
        occurrence=occurrence,
    )


def _truth(*, conditioned: bool = False) -> BusinessProcessGraph:
    concepts = {
        "activity": TruthConcept(
            id="activity",
            kind="activity",
            canonical_terms=["inspect"],
        )
    }
    condition = None
    if conditioned:
        concepts["condition"] = TruthConcept(
            id="condition",
            kind="condition",
            canonical_terms=["when fact"],
        )
        condition = ConceptRef(concept_id="condition")
    return canonicalize_truth_graph(
        BusinessProcessGraph(
            id="truth",
            concepts=concepts,
            nodes={
                "truth_node": TruthNode(
                    id="truth_node", activity=ConceptRef(concept_id="activity")
                )
            },
            edges={
                "loop": TruthEdge(
                    id="loop",
                    from_node="truth_node",
                    to_node="truth_node",
                    condition=condition,
                )
            },
        ),
        entry_node_ids=["truth_node"],
        exit_node_ids=["truth_node"],
    )


def _agent(
    *,
    activity_evidence: list[EvidenceRef] | None = None,
    marker_evidence: list[EvidenceRef] | None = None,
    edge_evidence: list[EvidenceRef] | None = None,
    condition_evidence: list[EvidenceRef] | None = None,
) -> AgentGraph:
    concepts = {
        "activity": AgentConcept(
            id="activity",
            kind="activity",
            display_label="inspect",
        )
    }
    condition: ConceptRef | AbsentType = ABSENT
    if condition_evidence is not None:
        concepts["condition"] = AgentConcept(
            id="condition",
            kind="condition",
            display_label="when fact",
        )
        condition = ConceptRef(
            concept_id="condition",
            evidence=condition_evidence,
        )
    actor: AbsentType = ABSENT
    if marker_evidence is not None:
        actor = AbsentType(evidence=marker_evidence)
    return AgentGraph(
        id="agent",
        concepts=concepts,
        nodes={
            "agent_node": AgentNode(
                id="agent_node",
                activity=ConceptRef(
                    concept_id="activity",
                    evidence=activity_evidence or [],
                ),
                actor=actor,
                system=ABSENT,
                reads=ABSENT,
                writes=ABSENT,
                necessity_rationale=ABSENT,
            )
        },
        edges={
            "loop": AgentEdge(
                id="loop",
                from_node="agent_node",
                to_node="agent_node",
                condition=condition,
                evidence=edge_evidence or [],
            )
        },
        start_node_ids=["agent_node"],
        end_node_ids=["agent_node"],
    )


def _context(
    *,
    observation_id: str = "obs_1",
    observation_text: str = "fact",
    observation_turn: int = 1,
    message_role: str = "user",
    message_content: str | None = "fact",
    messages_by_turn: dict[int, LedgerMessage] | None = None,
    protocol_completed: bool = True,
) -> InterviewEvaluationContext:
    messages = (
        {observation_turn: LedgerMessage(role=message_role, content=message_content)}
        if messages_by_turn is None
        else messages_by_turn
    )
    return InterviewEvaluationContext(
        observations=(
            ObservationRecord(
                id=observation_id,
                text=observation_text,
                turn=observation_turn,
            ),
        ),
        messages_by_turn=messages,
        protocol_completed=protocol_completed,
    )


def test_seed9004_interview_evaluator_matches_exactly_40_oracle_fields() -> None:
    truth = BusinessProcessGraph.model_validate_json(
        (FIXTURE_ROOT / "truth.json").read_text(encoding="utf-8")
    )
    agent = AgentGraph.model_validate_json(
        (FIXTURE_ROOT / "agent.json").read_text(encoding="utf-8")
    )
    context = InterviewEvaluationContext.model_validate_json(
        (FIXTURE_ROOT / "evaluation_context.json").read_text(encoding="utf-8")
    )
    expected = json.loads((FIXTURE_ROOT / "expected.json").read_text(encoding="utf-8"))

    actual = asdict(evaluate_interview(agent, truth, context))
    oracle = expected["oracle"]["fields"]

    assert len(INTERVIEW_FIELDS) == 40
    assert len(actual) == 40
    assert set(actual) == set(INTERVIEW_FIELDS)
    assert set(INTERVIEW_FIELDS) == set(oracle) - {"knowledge_coverage"}
    assert "knowledge_coverage" not in actual
    assert {field: actual[field] for field in INTERVIEW_FIELDS} == {
        field: oracle[field] for field in INTERVIEW_FIELDS
    }


def test_seed9004_context_is_minimal_raw_and_stably_serialized() -> None:
    path = FIXTURE_ROOT / "evaluation_context.json"
    text = path.read_text(encoding="utf-8")
    context = InterviewEvaluationContext.model_validate_json(text)

    assert set(ObservationRecord.model_fields) == {"id", "text", "turn"}
    assert set(LedgerMessage.model_fields) == {"role", "content"}
    assert set(InterviewEvaluationContext.model_fields) == {
        "observations",
        "messages_by_turn",
        "protocol_completed",
    }
    assert len(context.observations) == 14
    assert len(context.messages_by_turn) == 14
    assert all(
        "[Observation" not in observation.text for observation in context.observations
    )
    for observation in context.observations:
        message = context.messages_by_turn[observation.turn]
        assert message.role == "user"
        assert message.content == observation.text
    stable = (
        json.dumps(
            context.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    )
    assert text == stable


def test_valid_evidence_span_is_counted_and_passes_evidence() -> None:
    evidence = _evidence()
    result = evaluate_interview(
        _agent(activity_evidence=[evidence], edge_evidence=[evidence]),
        _truth(),
        _context(),
    )

    assert result.node_evidence_coverage == 1.0
    assert result.ref_evidence_coverage == 1.0
    assert result.edge_evidence_coverage == 1.0
    assert result.invalid_evidence_ref_count == 0
    assert result.invalid_observation_reference_count == 0
    assert result.provenance_authenticity_pass
    assert result.evidence_pass


def test_unknown_observation_id_is_invalid_at_each_source_validation_visit() -> None:
    result = evaluate_interview(
        _agent(activity_evidence=[_evidence("missing")]),
        _truth(),
        _context(),
    )

    assert result.invalid_evidence_ref_count == 2
    assert result.invalid_observation_reference_count == 2
    assert result.node_evidence_coverage == 0.0
    assert result.ref_evidence_coverage == 0.0
    assert not result.evidence_pass


@pytest.mark.parametrize(
    "evidence",
    [
        _evidence(quote="not present"),
        _evidence(occurrence=1),
    ],
    ids=["invalid-quote", "invalid-occurrence"],
)
def test_invalid_quote_or_occurrence_is_an_invalid_evidence_span(
    evidence: EvidenceRef,
) -> None:
    result = evaluate_interview(
        _agent(activity_evidence=[evidence]),
        _truth(),
        _context(),
    )

    assert result.invalid_evidence_ref_count == 2
    assert result.invalid_observation_reference_count == 0
    assert not result.evidence_pass


@pytest.mark.parametrize(
    ("message_role", "message_content", "messages_by_turn"),
    [
        ("assistant", "fact", None),
        ("user", "different", None),
        ("user", None, {}),
    ],
    ids=["role-mismatch", "text-mismatch", "missing-message-turn"],
)
def test_observation_authenticity_requires_user_raw_text_at_observation_turn(
    message_role: str,
    message_content: str | None,
    messages_by_turn: dict[int, LedgerMessage] | None,
) -> None:
    result = evaluate_interview(
        _agent(activity_evidence=[_evidence()], edge_evidence=[_evidence()]),
        _truth(),
        _context(
            message_role=message_role,
            message_content=message_content,
            messages_by_turn=messages_by_turn,
        ),
    )

    assert result.authentic_observation_count == 0
    assert result.invalid_observation_source_count == 1
    assert not result.provenance_authenticity_pass
    assert not result.evidence_pass


def test_orphan_observation_is_counted_even_when_its_source_is_authentic() -> None:
    context = _context(
        observation_id="orphan",
        observation_text="orphan text",
        message_content="orphan text",
    )
    result = evaluate_interview(_agent(), _truth(), context)

    assert result.authentic_observation_count == 1
    assert result.invalid_observation_source_count == 0
    assert result.orphan_observation_count == 1


def test_marker_evidence_counts_for_node_coverage() -> None:
    result = evaluate_interview(
        _agent(marker_evidence=[_evidence()]),
        _truth(),
        _context(),
    )

    assert result.node_evidence_coverage == 1.0
    assert result.ref_evidence_coverage == 0.0
    assert result.invalid_evidence_ref_count == 0
    assert result.orphan_observation_count == 0


def test_edge_evidence_coverage_uses_edge_evidence_refs() -> None:
    evidence = _evidence()
    result = evaluate_interview(
        _agent(activity_evidence=[evidence], edge_evidence=[evidence]),
        _truth(),
        _context(),
    )

    assert result.edge_evidence_coverage == 1.0


def test_condition_value_evidence_is_in_orphan_reference_tracking() -> None:
    evidence = _evidence()
    result = evaluate_interview(
        _agent(condition_evidence=[evidence]),
        _truth(conditioned=True),
        _context(),
    )

    assert result.orphan_observation_count == 0
    # The source edge coverage denominator checks AgentEdge.evidence, not the
    # condition ConceptRef evidence that is used by orphan tracking.
    assert result.edge_evidence_coverage == 0.0


def test_protocol_false_is_exposed_without_changing_graph_passes() -> None:
    result = evaluate_interview(
        _agent(),
        _truth(),
        _context(protocol_completed=False),
    )

    assert result.protocol_completed is False
    assert result.protocol_pass is False
    assert result.reconstruction_pass is True
    assert result.structural_pass is True
    assert result.quality_pass is True


def test_evidence_failure_does_not_change_graph_reconstruction_score() -> None:
    result = evaluate_interview(
        _agent(
            activity_evidence=[_evidence("missing")],
            edge_evidence=[_evidence()],
        ),
        _truth(),
        _context(),
    )

    assert result.evidence_pass is False
    assert result.graph_created
    assert result.graph_valid
    assert result.reconstruction_pass
    assert result.structural_pass
    assert result.quality_pass


def test_interview_evaluation_does_not_mutate_graphs_or_context() -> None:
    evidence = _evidence()
    agent = _agent(activity_evidence=[evidence], edge_evidence=[evidence])
    truth = _truth()
    context = _context()
    agent_before = agent.model_dump(mode="json")
    truth_before = truth.model_dump(mode="json")
    context_before = context.model_dump(mode="json")

    evaluate_interview(agent, truth, context)

    assert agent.model_dump(mode="json") == agent_before
    assert truth.model_dump(mode="json") == truth_before
    assert context.model_dump(mode="json") == context_before
