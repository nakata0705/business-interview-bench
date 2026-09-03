"""Deterministic Phase 13 core runtime and graph mutation contracts."""

# The workspace-level auxiliary resolver may not see freshly added siblings;
# project-level ``uv run pyright`` is authoritative for this package.
# pyright: reportMissingImports=false

from __future__ import annotations

import json

import pytest

from business_interview.graph_mutations import (
    GraphMutationError,
    add_edge,
    add_node,
    attach_evidence,
    define_concept,
    remove_concept,
    remove_edge,
    remove_node,
    set_edge_condition,
    set_node_absent,
    set_node_dont_know,
    set_node_property,
    update_concept,
    update_edge,
    update_node,
)
from business_interview.models import (
    STRUCTURAL_SINK_ID,
    STRUCTURAL_SOURCE_ID,
    UNSET,
    AgentGraph,
    ConceptRef,
    EvidenceRef,
)
from business_interview.runtime import (
    InterviewRuntimeError,
    LiveInterviewStore,
    apply_agent_graph_mutation,
    create_live_interview_store,
    ingest_stakeholder_response,
    mark_interview_complete,
    mark_max_turn_exhausted,
)
from business_interview.stakeholders import (
    ConceptAlignmentAssertion,
    KnowledgeConceptRef,
    PlannedResponseItem,
    SemanticAnnotation,
    SemanticResponsePlan,
    StakeholderEdge,
    StakeholderKnowledge,
    StakeholderKnowledgeConcept,
    StakeholderKnowledgeGraph,
    StakeholderNode,
    StakeholderResponse,
    TerminologyConfirmation,
    validate_stakeholder_knowledge,
)

_SOURCE_EDGE = "__tau2_structural_boundary__source_001"
_SINK_EDGE = "__tau2_structural_boundary__sink_001"


def _knowledge() -> StakeholderKnowledge:
    graph = StakeholderKnowledgeGraph(
        nodes={
            STRUCTURAL_SOURCE_ID: StakeholderNode(
                id=STRUCTURAL_SOURCE_ID,
                structural=True,
                structural_role="source",
                protected=True,
            ),
            "skn_001": StakeholderNode(
                id="skn_001",
                activity=KnowledgeConceptRef(concept_id="skc_activity"),
            ),
            "skn_002": StakeholderNode(id="skn_002"),
            STRUCTURAL_SINK_ID: StakeholderNode(
                id=STRUCTURAL_SINK_ID,
                structural=True,
                structural_role="sink",
                protected=True,
            ),
        },
        edges={
            _SOURCE_EDGE: StakeholderEdge(
                id=_SOURCE_EDGE,
                from_node=STRUCTURAL_SOURCE_ID,
                to_node="skn_001",
                edge_kind="structural_boundary",
                structural_only=True,
                protected=True,
            ),
            "ske_001": StakeholderEdge(
                id="ske_001",
                from_node="skn_001",
                to_node="skn_002",
            ),
            _SINK_EDGE: StakeholderEdge(
                id=_SINK_EDGE,
                from_node="skn_002",
                to_node=STRUCTURAL_SINK_ID,
                edge_kind="structural_boundary",
                structural_only=True,
                protected=True,
            ),
        },
        concepts={
            "skc_activity": StakeholderKnowledgeConcept(
                id="skc_activity",
                truth_concept_id="me",
                kind="activity",
                description="review requests",
                terms=("review requests",),
            )
        },
        node_truth_ids={"skn_001": "me"},
        edge_truth_ids={"ske_001": "truth_edge"},
    )
    knowledge = StakeholderKnowledge(graph=graph)
    validate_stakeholder_knowledge(knowledge)
    return knowledge


def _validated_response() -> tuple[SemanticResponsePlan, StakeholderResponse]:
    plan = SemanticResponsePlan(
        items=(
            PlannedResponseItem(
                semantic_id="node:skn_001:activity",
                mode="value",
            ),
        )
    )
    response = StakeholderResponse(
        message="I review requests. Yes.",
        annotations=(
            SemanticAnnotation(
                semantic_id="node:skn_001:activity",
                mode="value",
                quote="review requests",
            ),
        ),
        alignments=(
            ConceptAlignmentAssertion(
                semantic_id="skc_activity",
                quote="Yes.",
                act="confirm",
            ),
        ),
        terminology=(
            TerminologyConfirmation(
                semantic_id="skc_activity",
                proposed_term="review requests",
                proposal_turn=0,
                proposal_quote="May I call this review requests?",
                quote="Yes.",
            ),
        ),
    )
    return plan, response


def _asked_store() -> LiveInterviewStore:
    store = create_live_interview_store("test-scenario")
    store = store.record_candidate_turn()
    return store.record_candidate_question("May I call this review requests?")


def test_live_ingestion_is_atomic_and_preserves_public_provenance() -> None:
    store = _asked_store()
    plan, response = _validated_response()
    invalid = response.model_copy(update={"annotations": ()})

    with pytest.raises(ValueError, match="missing planned"):
        ingest_stakeholder_response(store, _knowledge(), plan, invalid)
    assert store.observations == ()
    assert store.semantic_ledger.entries == ()
    assert store.public_message_ledger[-1].role == "assistant"

    updated = ingest_stakeholder_response(store, _knowledge(), plan, response)
    observation = updated.observations[-1]
    entry = updated.semantic_ledger.entries[-1]
    assert observation.id == "obs_1"
    assert observation.turn == 1
    assert observation.text == response.message
    assert entry.observation_id == observation.id
    assert entry.public_message_turn == observation.turn
    assert entry.plan == plan
    assert entry.annotations == response.annotations
    assert entry.alignments == response.alignments
    assert entry.terminology == response.terminology
    assert updated.public_message_ledger[-1].content == response.message
    assert "annotations" not in json.dumps(
        [message.model_dump(mode="json") for message in updated.public_messages]
    )
    context = updated.evaluation_context()
    assert context.observations == (observation,)
    assert context.messages_by_turn[observation.turn].content == response.message
    assert context.messages_by_turn[observation.turn].role == "user"
    assert not context.protocol_completed


def test_live_store_json_round_trip_and_completion_protocol() -> None:
    store = _asked_store()
    plan, response = _validated_response()
    store = store.ingest_stakeholder_response(_knowledge(), plan, response)
    restored = LiveInterviewStore.model_validate(store.model_dump(mode="json"))
    assert restored.model_dump(mode="json") == store.model_dump(mode="json")

    completed = mark_interview_complete(restored, "candidate finished")
    assert completed.protocol_completed
    assert completed.protocol_state.status == "completed"
    with pytest.raises(InterviewRuntimeError, match="terminal"):
        completed.record_candidate_turn()
    with pytest.raises(InterviewRuntimeError, match="terminal"):
        completed.record_candidate_question("another question")


def test_max_turn_exhaustion_is_incomplete_not_completion() -> None:
    store = create_live_interview_store("test-scenario", max_turns=1)
    store = store.record_candidate_turn()
    store = store.record_candidate_question("Question")
    store = store.ingest_stakeholder_response(
        _knowledge(),
        SemanticResponsePlan(),
        StakeholderResponse(message="Answer."),
    )
    exhausted = mark_max_turn_exhausted(store)
    assert exhausted.protocol_state.status == "incomplete"
    assert not exhausted.protocol_completed
    assert exhausted.termination_reason == "max_turns_exhausted"


def test_candidate_turns_and_candidate_steps_have_separate_bounds() -> None:
    store = create_live_interview_store(
        "test-scenario",
        max_interview_turns=2,
        max_candidate_steps_per_turn=2,
    )
    store = store.record_candidate_turn().record_candidate_step()
    next_turn = store.record_candidate_turn()
    assert next_turn.candidate_turns == 2
    assert next_turn.candidate_steps == 0
    next_turn = next_turn.record_candidate_step().record_candidate_step()
    with pytest.raises(InterviewRuntimeError, match="candidate step count"):
        next_turn.record_candidate_step()


def test_graph_mutation_error_reason_survives_runtime_wrapper() -> None:
    store = create_live_interview_store("test-scenario")
    with pytest.raises(InterviewRuntimeError, match="node does not exist"):
        apply_agent_graph_mutation(
            store,
            lambda graph: remove_node(graph, "missing"),
        )


def test_pure_node_and_concept_mutations_preserve_input_and_states() -> None:
    original = AgentGraph()
    graph = define_concept(
        original,
        concept_id="c_activity",
        kind="activity",
        display_label="Review",
    )
    graph = update_concept(
        graph,
        "c_activity",
        updates={"display_label": "Review requests"},
    )
    graph = add_node(graph, "n1")
    graph = update_node(graph, "n1", updates={"activity": "c_activity"})
    graph = set_node_absent(graph, "n1", "actor")
    graph = set_node_dont_know(graph, "n1", "system")
    graph = set_node_property(graph, "n1", "reads", [])
    assert original.nodes == {}
    activity = graph.nodes["n1"].activity
    assert isinstance(activity, ConceptRef)
    assert activity == ConceptRef(concept_id="c_activity")
    assert activity.evidence == []
    assert graph.nodes["n1"].actor.state == "absent"
    assert graph.nodes["n1"].system.state == "dont_know"
    assert graph.nodes["n1"].reads == []

    graph = add_node(graph, "n2")
    graph = add_edge(graph, "e1", from_node="n1", to_node="n2")
    graph = update_edge(graph, "e1", updates={"condition": "c_activity"})
    graph = set_edge_condition(graph, "e1", "DONT_KNOW")
    assert graph.edges["e1"].condition.state == "dont_know"
    graph = remove_edge(graph, "e1")
    graph = set_node_property(graph, "n1", "activity", UNSET)
    graph = remove_node(graph, "n2")
    graph = remove_node(graph, "n1")
    graph = remove_concept(graph, "c_activity")
    assert graph.nodes == {} and graph.edges == {} and graph.concepts == {}


def test_store_rejects_evidence_bypasses_and_forged_persisted_state() -> None:
    store = _asked_store()
    plan, response = _validated_response()
    store = store.ingest_stakeholder_response(_knowledge(), plan, response)
    graph = define_concept(
        AgentGraph(),
        concept_id="c_activity",
        kind="activity",
        display_label="Review",
    )
    graph = add_node(graph, "n1")
    graph = set_node_absent(
        graph,
        "n1",
        "actor",
        evidence=[EvidenceRef(observation_id="missing", quote="review")],
    )
    with pytest.raises(InterviewRuntimeError, match="unknown observation"):
        store.apply_agent_graph(graph)
    forged = store.model_dump(mode="json")
    forged["public_message_ledger"][0]["turn"] = 99
    with pytest.raises(ValueError, match="contiguous"):
        LiveInterviewStore.model_validate(forged)

    forged = store.model_dump(mode="json")
    forged["semantic_ledger"]["entries"][0]["annotations"][0]["quote"] = "wrong"
    with pytest.raises(ValueError, match="exact observation span"):
        LiveInterviewStore.model_validate(forged)

    forged = _asked_store().model_dump(mode="json")
    forged["protocol_state"] = {
        "status": "completed",
        "completion_reason": "forged",
        "terminal_turn": 1,
    }
    with pytest.raises(ValueError, match="pending question"):
        LiveInterviewStore.model_validate(forged)


def test_mutations_reject_invalid_references_and_attach_exact_observation() -> None:
    graph = define_concept(
        AgentGraph(),
        concept_id="c_activity",
        kind="activity",
        display_label="Review",
    )
    graph = add_node(graph, "n1")
    graph = set_node_property(graph, "n1", "activity", "c_activity")
    evidence = EvidenceRef(observation_id="obs_1", quote="review")
    graph = attach_evidence(
        graph,
        "node:n1:activity",
        evidence,
        observation_ids={"obs_1"},
        observation_texts={"obs_1": "review"},
    )
    attached_activity = graph.nodes["n1"].activity
    assert isinstance(attached_activity, ConceptRef)
    assert attached_activity.evidence == [evidence]

    with pytest.raises(GraphMutationError, match="unknown observation"):
        attach_evidence(
            graph,
            "node:n1:activity",
            observation_id="missing",
            observation_ids={"obs_1"},
        )
    with pytest.raises(GraphMutationError, match="exact span"):
        attach_evidence(
            graph,
            "node:n1:activity",
            observation_id="obs_1",
            quote="not in observation",
            observation_texts={"obs_1": "review requests"},
        )

    graph = add_node(graph, "n2")
    graph = add_edge(graph, "e1", from_node="n1", to_node="n2")
    graph = set_edge_condition(graph, "e1", "c_activity")
    graph = attach_evidence(
        graph,
        edge_id="e1",
        property_name="condition",
        observation_id="obs_1",
        quote="review",
        observation_ids={"obs_1"},
        observation_texts={"obs_1": "review"},
    )
    condition = graph.edges["e1"].condition
    assert isinstance(condition, ConceptRef)
    assert condition.evidence == [evidence]
    with pytest.raises(GraphMutationError, match="unknown concept"):
        set_node_property(graph, "n1", "activity", "missing")
    with pytest.raises(GraphMutationError, match="does not exist"):
        add_edge(graph, "e2", from_node="n1", to_node="missing")
    with pytest.raises(GraphMutationError, match="incident edges"):
        remove_node(graph, "n1")
