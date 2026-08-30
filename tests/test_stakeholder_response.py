"""Core-only tests for stakeholder response plans, sidecars, and prompts."""

# The workspace-level auxiliary resolver may not see freshly added modules.
# Project-level ``uv run pyright`` remains the authoritative check.
# pyright: reportMissingImports=false

from __future__ import annotations

import json
from typing import cast

import pytest
from pydantic import ValidationError

from business_interview.models import (
    STRUCTURAL_SINK_ID,
    STRUCTURAL_SOURCE_ID,
)
from business_interview.stakeholders.knowledge import (
    DONT_KNOW,
    KnowledgeConceptRef,
    StakeholderEdge,
    StakeholderKnowledge,
    StakeholderKnowledgeConcept,
    StakeholderKnowledgeGraph,
    StakeholderNode,
    validate_stakeholder_knowledge,
)
from business_interview.stakeholders.prompting import render_knowledge_prompt
from business_interview.stakeholders.response import (
    ConceptAlignmentAssertion,
    PlannedResponseItem,
    ResponseParseError,
    ResponseValidationError,
    SemanticAnnotation,
    SemanticMode,
    SemanticResponsePlan,
    StakeholderResponse,
    TerminologyConfirmation,
    canonical_semantic_mode,
    parse_semantic_response_plan,
    parse_stakeholder_response,
    validate_response_plan,
    validate_stakeholder_response,
)

_SOURCE_EDGE = "__tau2_structural_boundary__source_001"
_SINK_EDGE = "__tau2_structural_boundary__sink_001"


def _ref(concept_id: str) -> KnowledgeConceptRef:
    return KnowledgeConceptRef(concept_id=concept_id)


def _knowledge() -> StakeholderKnowledge:
    concepts = {
        "skc_activity": StakeholderKnowledgeConcept(
            id="skc_activity",
            truth_concept_id="truth_activity",
            kind="activity",
            description="review customer requests",
            terms=("review request",),
        ),
        "skc_data": StakeholderKnowledgeConcept(
            id="skc_data",
            truth_concept_id="truth_hidden_data",
            kind="data",
            description=DONT_KNOW,
            terms=DONT_KNOW,
        ),
        "skc_condition": StakeholderKnowledgeConcept(
            id="skc_condition",
            truth_concept_id="truth_condition",
            kind="condition",
            description="approval state",
            terms=("approved",),
        ),
        "skc_result": StakeholderKnowledgeConcept(
            id="skc_result",
            truth_concept_id="truth_result",
            kind="data",
            description="reply record",
            terms=("reply",),
        ),
    }
    nodes = {
        STRUCTURAL_SOURCE_ID: StakeholderNode(
            id=STRUCTURAL_SOURCE_ID,
            structural=True,
            structural_role="source",
            protected=True,
        ),
        "skn_001": StakeholderNode(
            id="skn_001",
            activity=_ref("skc_activity"),
            actor=None,
            system=DONT_KNOW,
            reads=(_ref("skc_data"),),
            writes=DONT_KNOW,
        ),
        "skn_002": StakeholderNode(
            id="skn_002",
            activity=_ref("skc_result"),
        ),
        STRUCTURAL_SINK_ID: StakeholderNode(
            id=STRUCTURAL_SINK_ID,
            structural=True,
            structural_role="sink",
            protected=True,
        ),
    }
    edges = {
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
            condition=_ref("skc_condition"),
        ),
        _SINK_EDGE: StakeholderEdge(
            id=_SINK_EDGE,
            from_node="skn_002",
            to_node=STRUCTURAL_SINK_ID,
            edge_kind="structural_boundary",
            structural_only=True,
            protected=True,
        ),
    }
    knowledge = StakeholderKnowledge(
        graph=StakeholderKnowledgeGraph(
            id="truth-workflow-secret-name",
            name="private stakeholder world",
            nodes=nodes,
            edges=edges,
            concepts=concepts,
            node_truth_ids={"skn_001": "truth_node_secret"},
            edge_truth_ids={"ske_001": "truth_edge_secret"},
        )
    )
    validate_stakeholder_knowledge(knowledge)
    return knowledge


def _plan(*items: tuple[str, str]) -> SemanticResponsePlan:
    return SemanticResponsePlan(
        items=tuple(
            PlannedResponseItem(
                semantic_id=semantic_id,
                mode=cast(SemanticMode, mode),
            )
            for semantic_id, mode in items
        )
    )


def _response(
    message: str,
    *annotations: SemanticAnnotation,
    alignments: tuple[ConceptAlignmentAssertion, ...] = (),
    terminology: tuple[TerminologyConfirmation, ...] = (),
) -> StakeholderResponse:
    return StakeholderResponse(
        message=message,
        annotations=annotations,
        alignments=alignments,
        terminology=terminology,
    )


def test_canonical_modes_cover_values_absence_unknown_existence_and_mention() -> None:
    knowledge = _knowledge()

    assert canonical_semantic_mode(knowledge, "node:skn_001") == "exists"
    assert canonical_semantic_mode(knowledge, "edge:ske_001") == "exists"
    assert canonical_semantic_mode(knowledge, "skc_activity") == "mention"
    assert canonical_semantic_mode(knowledge, "node:skn_001:activity") == "value"
    assert canonical_semantic_mode(knowledge, "node:skn_001:actor") == "absent"
    assert canonical_semantic_mode(knowledge, "node:skn_001:system") == "dont_know"
    assert canonical_semantic_mode(knowledge, "node:skn_001:reads:skc_data") == "value"
    assert canonical_semantic_mode(knowledge, "edge:ske_001:condition") == "value"


def test_response_models_are_immutable_and_parse_json() -> None:
    plan = parse_semantic_response_plan(
        '{"items": [{"semantic_id": "node:skn_001:activity", "mode": "value"}]}'
    )
    assert isinstance(plan.items, tuple)
    with pytest.raises(ValidationError):
        plan.items += (PlannedResponseItem(semantic_id="skc_activity", mode="mention"),)

    response = parse_stakeholder_response(
        json.dumps(
            {
                "message": "I review requests.",
                "annotations": [
                    {
                        "semantic_id": "node:skn_001:activity",
                        "mode": "value",
                        "quote": "review requests",
                        "occurrence": 0,
                    }
                ],
                "alignments": [],
                "terminology": [],
            }
        )
    )
    assert isinstance(response.annotations, tuple)
    with pytest.raises(ValidationError):
        response.message = "changed"


def test_valid_plan_is_accepted() -> None:
    plan = _plan(
        ("node:skn_001:activity", "value"),
        ("node:skn_001:system", "dont_know"),
        ("skc_activity", "mention"),
    )
    assert validate_response_plan(_knowledge(), plan) is plan


@pytest.mark.parametrize(
    ("semantic_id", "mode"),
    [
        ("node:skn_001:activity", "dont_know"),
        ("node:skn_001:actor", "value"),
        ("node:skn_001:system", "value"),
        ("node:skn_001", "value"),
        ("skc_activity", "value"),
        ("edge:ske_001:condition", "absent"),
    ],
)
def test_wrong_plan_mode_is_rejected(semantic_id: str, mode: str) -> None:
    with pytest.raises(ResponseValidationError, match="requires"):
        validate_response_plan(_knowledge(), _plan((semantic_id, mode)))


def test_unknown_and_truth_only_ids_are_rejected() -> None:
    for semantic_id in ("node:missing", "node:truth_node_secret", "truth_activity"):
        with pytest.raises(ResponseValidationError, match="not resolvable"):
            validate_response_plan(_knowledge(), _plan((semantic_id, "exists")))


def test_empty_plan_and_empty_annotations_are_allowed() -> None:
    knowledge = _knowledge()
    plan = SemanticResponsePlan()
    assert validate_response_plan(knowledge, plan) is plan
    response = _response("Hello.")
    assert validate_stakeholder_response(knowledge, plan, response) is response


def test_valid_response_allows_multiple_spans_and_private_concept_events() -> None:
    knowledge = _knowledge()
    plan = _plan(
        ("node:skn_001:activity", "value"),
        ("edge:ske_001", "exists"),
        ("node:skn_002:activity", "value"),
    )
    response = _response(
        "I review requests, then I send replies. Yes.",
        SemanticAnnotation(
            semantic_id="node:skn_001:activity",
            mode="value",
            quote="review requests",
        ),
        SemanticAnnotation(
            semantic_id="node:skn_001:activity",
            mode="value",
            quote="review",
        ),
        SemanticAnnotation(
            semantic_id="edge:ske_001",
            mode="exists",
            quote="then",
        ),
        SemanticAnnotation(
            semantic_id="node:skn_002:activity",
            mode="value",
            quote="send replies",
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
                proposed_term="work item",
                quote="Yes.",
            ),
        ),
    )

    assert validate_stakeholder_response(knowledge, plan, response) is response


def test_missing_planned_annotation_is_rejected() -> None:
    with pytest.raises(ResponseValidationError, match="missing planned"):
        validate_stakeholder_response(
            _knowledge(),
            _plan(("node:skn_001:activity", "value")),
            _response("I review requests."),
        )


def test_unplanned_annotation_is_rejected() -> None:
    response = _response(
        "I review requests.",
        SemanticAnnotation(
            semantic_id="node:skn_001:actor",
            mode="absent",
            quote="I",
        ),
    )
    with pytest.raises(ResponseValidationError, match="unplanned"):
        validate_stakeholder_response(
            _knowledge(),
            _plan(("node:skn_001:activity", "value")),
            response,
        )


def test_annotation_mode_must_match_knowledge() -> None:
    response = _response(
        "I do not know.",
        SemanticAnnotation(
            semantic_id="node:skn_001:system",
            mode="value",
            quote="I do not know",
        ),
    )
    with pytest.raises(ResponseValidationError, match="requires 'dont_know'"):
        validate_stakeholder_response(
            _knowledge(),
            _plan(("node:skn_001:system", "dont_know")),
            response,
        )


def test_public_message_cannot_leak_local_or_truth_ids() -> None:
    plan = _plan(("node:skn_001:activity", "value"))
    for leaked in ("node:skn_001:activity", "truth_activity"):
        response = _response(
            leaked,
            SemanticAnnotation(
                semantic_id="node:skn_001:activity",
                mode="value",
                quote=leaked,
            ),
        )
        with pytest.raises(ResponseValidationError, match="private identifier"):
            validate_stakeholder_response(_knowledge(), plan, response)


@pytest.mark.parametrize(
    "response",
    [
        _response(
            "I review requests.",
            SemanticAnnotation(
                semantic_id="node:skn_001:activity",
                mode="value",
                quote="not present",
            ),
        ),
        _response(
            "I review requests.",
            SemanticAnnotation(
                semantic_id="node:skn_001:activity",
                mode="value",
                quote="review",
                occurrence=1,
            ),
        ),
    ],
)
def test_quote_or_occurrence_mismatch_is_rejected(
    response: StakeholderResponse,
) -> None:
    with pytest.raises(ResponseValidationError, match="exact span"):
        validate_stakeholder_response(
            _knowledge(),
            _plan(("node:skn_001:activity", "value")),
            response,
        )


def test_alignment_must_target_a_knowledge_concept() -> None:
    knowledge = _knowledge()
    plan = SemanticResponsePlan()
    valid = _response(
        "Yes.",
        alignments=(
            ConceptAlignmentAssertion(
                semantic_id="skc_activity",
                quote="Yes.",
                act="partial",
            ),
        ),
    )
    assert validate_stakeholder_response(knowledge, plan, valid) is valid

    invalid = _response(
        "Yes.",
        alignments=(
            ConceptAlignmentAssertion(
                semantic_id="node:skn_001",
                quote="Yes.",
                act="confirm",
            ),
        ),
    )
    with pytest.raises(ResponseValidationError, match="concept"):
        validate_stakeholder_response(knowledge, plan, invalid)


def test_terminology_requires_a_knowledge_concept_and_nonempty_term() -> None:
    knowledge = _knowledge()
    valid = _response(
        "Yes.",
        terminology=(
            TerminologyConfirmation(
                semantic_id="skc_activity",
                proposed_term="request review",
                quote="Yes.",
            ),
        ),
    )
    assert (
        validate_stakeholder_response(knowledge, SemanticResponsePlan(), valid) is valid
    )

    with pytest.raises(ValidationError):
        TerminologyConfirmation(
            semantic_id="skc_activity",
            proposed_term=" ",
            quote="Yes.",
        )


def test_prompt_renders_only_local_knowledge_and_distinguishes_slot_states() -> None:
    prompt = render_knowledge_prompt(_knowledge())

    assert "node:skn_001" in prompt
    assert "edge:ske_001" in prompt
    assert "skc_activity" in prompt
    assert "review request" in prompt
    assert 'state="value"' in prompt
    assert 'state="absent"' in prompt
    assert 'state="dont_know"' in prompt
    assert "truth_node_secret" not in prompt
    assert "truth_edge_secret" not in prompt
    assert "truth_activity" not in prompt
    assert "truth-workflow-secret-name" not in prompt
    assert "skn_hidden" not in prompt


def test_json_parsing_is_strict_and_does_not_repair_fences() -> None:
    with pytest.raises(ResponseParseError):
        parse_semantic_response_plan('```json\n{"items": []}\n```')
    with pytest.raises(ResponseParseError):
        parse_stakeholder_response("not json")
