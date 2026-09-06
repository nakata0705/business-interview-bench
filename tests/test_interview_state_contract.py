"""Contract tests for the first InterviewState/tool vertical slice."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from business_interview.interview_state import (
    Claim,
    EvidenceCitation,
    EvidenceRef,
    InformationValue,
    InterviewHarness,
    InterviewState,
    InterviewStateError,
    Utterance,
)
from business_interview.interview_tools import (
    CompleteInterviewInput,
    ConnectProcessStepsInput,
    EntityInput,
    InterviewToolExecutor,
    RecordProcessStepInput,
    RecordResourceUsageInput,
    ReviseRecordInput,
    SystemInput,
    ValueInput,
    get_tool_definitions,
    tool_schemas,
)
from business_interview.prototype import replay_case_file

# pyright: reportMissingImports=false

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CASE_DIR = PROJECT_ROOT / "examples" / "interview_state" / "cases"


def _harness(text: str = "The coordinator updates the tracker.") -> InterviewHarness:
    harness = InterviewHarness()
    harness.register_utterance(Utterance(id="u1", speaker="stakeholder", text=text))
    return harness


def _citation(
    text: str = "The coordinator updates the tracker.",
    *,
    support: str = "supports",
) -> EvidenceCitation:
    return EvidenceCitation(
        utterance_id="u1",
        start=0,
        end=len(text),
        quote=text,
        semantic_support=support,  # type: ignore[arg-type]
    )


def _step(executor: InterviewToolExecutor) -> None:
    receipt = executor.record_process_step(
        RecordProcessStepInput(
            step_id="step1",
            activity=ValueInput(state="value", value="review request"),
            actor=EntityInput(id="actor1", label="coordinator"),
            evidence=(_citation(),),
        )
    )
    assert receipt.ok


def test_utterances_are_harness_owned_and_exact_evidence_is_range_checked() -> None:
    harness = _harness()
    evidence = harness.issue_evidence(_citation())
    assert evidence.evidence_id == "ev_0001"
    assert evidence.start == 0
    assert evidence.end == len(evidence.quote)

    with pytest.raises(InterviewStateError, match="quote does not match"):
        harness.issue_evidence(
            EvidenceCitation(
                utterance_id="u1",
                start=0,
                end=3,
                quote="not",
            )
        )
    with pytest.raises(InterviewStateError, match="already exists"):
        harness.register_utterance(
            Utterance(id="u1", speaker="interviewer", text="changed")
        )
    assert harness.state.utterances[0].text == "The coordinator updates the tracker."


def test_confirmed_is_not_confidence_and_requires_explicit_support() -> None:
    evidence = EvidenceRef(
        evidence_id="ev_1",
        utterance_id="u1",
        start=0,
        end=4,
        quote="fact",
    )
    with pytest.raises(ValueError, match="marked supports"):
        Claim(
            id="claim1",
            record_type="process_step",
            target_id="step1",
            predicate="activity",
            statement="The step is supported.",
            value=InformationValue(state="value", value="review"),
            evidence=(evidence,),
            status="confirmed",
        )


def test_invalid_reference_or_quote_does_not_partially_apply() -> None:
    harness = _harness()
    executor = InterviewToolExecutor(harness)
    _step(executor)
    before = executor.state.model_dump(mode="json")

    invalid_reference = executor.record_resource_usage(
        RecordResourceUsageInput(
            usage_id="usage1",
            process_step_id="missing_step",
            system=SystemInput(id="system1", label="tracker"),
            data_type=EntityInput(id="data1", label="request"),
            crud="update",
            evidence=(_citation(),),
        )
    )
    assert not invalid_reference.ok
    assert executor.state.model_dump(mode="json") == before

    invalid_quote = executor.record_resource_usage(
        RecordResourceUsageInput(
            usage_id="usage1",
            process_step_id="step1",
            system=SystemInput(id="system1", label="tracker"),
            data_type=EntityInput(id="data1", label="request"),
            crud="update",
            evidence=(
                EvidenceCitation(
                    utterance_id="u1",
                    start=0,
                    end=5,
                    quote="wrong",
                ),
            ),
        )
    )
    assert not invalid_quote.ok
    assert executor.state.model_dump(mode="json") == before


def test_correction_preserves_old_claim_but_current_projection_is_unique() -> None:
    harness = _harness()
    executor = InterviewToolExecutor(harness)
    _step(executor)
    usage = executor.record_resource_usage(
        RecordResourceUsageInput(
            usage_id="usage1",
            process_step_id="step1",
            system=SystemInput(id="system1", label="tracker"),
            data_type=EntityInput(id="data1", label="request"),
            crud="unknown",
            evidence=(_citation(),),
        )
    )
    assert usage.ok
    revised = executor.revise_record(
        ReviseRecordInput(
            record_id="claim:usage1:crud",
            replacement_id="claim:usage1:crud:revision1",
            statement="The tracker is read during review.",
            value=ValueInput(state="value", value="read"),
            correction_note="The stakeholder corrected the CRUD description.",
            evidence=(_citation(),),
            claim_status="confirmed",
        )
    )
    assert revised.ok
    old = next(item for item in executor.state.claims if item.id == "claim:usage1:crud")
    current = next(
        item
        for item in executor.state.claims
        if item.id == "claim:usage1:crud:revision1"
    )
    assert old.status == "rejected"
    assert current.supersedes == old.id
    assert current.evidence[0].quote == old.evidence[0].quote
    assert executor.state.business_model.data_operations[0].crud == "read"
    assert all(
        operation.crud != "unknown"
        for operation in executor.state.business_model.data_operations
    )


def test_unknown_crud_is_not_inferred_from_a_process_step() -> None:
    harness = _harness("I send the request by email.")
    executor = InterviewToolExecutor(harness)
    send = executor.record_process_step(
        RecordProcessStepInput(
            step_id="send",
            activity=ValueInput(state="value", value="send request"),
            evidence=(
                EvidenceCitation(
                    utterance_id="u1",
                    start=2,
                    end=28,
                    quote="send the request by email.",
                    semantic_support="supports",
                ),
            ),
        )
    )
    assert send.ok
    usage = executor.record_resource_usage(
        RecordResourceUsageInput(
            usage_id="send_usage",
            process_step_id="send",
            system=SystemInput(id="email", label="email"),
            data_type=EntityInput(id="request", label="request"),
            crud="unknown",
            evidence=(
                EvidenceCitation(
                    utterance_id="u1",
                    start=2,
                    end=28,
                    quote="send the request by email.",
                    semantic_support="supports",
                ),
            ),
        )
    )
    assert usage.ok
    assert executor.state.business_model.data_operations[0].crud == "unknown"


def test_source_sink_are_not_normal_process_edges() -> None:
    harness = _harness()
    executor = InterviewToolExecutor(harness)
    _step(executor)
    invalid = executor.connect_process_steps(
        ConnectProcessStepsInput(
            flow_id="bad",
            from_step_id="SOURCE",
            to_step_id="step1",
            kind="normal",
            evidence=(_citation(),),
        )
    )
    assert not invalid.ok
    assert not executor.state.business_model.flows
    valid = executor.connect_process_steps(
        ConnectProcessStepsInput(
            flow_id="source",
            from_step_id="SOURCE",
            to_step_id="step1",
            kind="source_boundary",
            evidence=(_citation(),),
        )
    )
    assert valid.ok
    assert executor.state.business_model.flows[0].kind == "source_boundary"


def test_completion_does_not_claim_stakeholder_approval() -> None:
    harness = _harness()
    executor = InterviewToolExecutor(harness)
    result = executor.complete_interview(
        CompleteInterviewInput(
            termination_reason="time limit",
            content_completeness="unknown",
        )
    )
    assert result.ok
    assert executor.state.completion.status == "ended"
    assert not executor.state.completion.stakeholder_confirmed
    assert executor.state.completion.confirmation_evidence == ()
    late = executor.record_process_step(
        RecordProcessStepInput(
            step_id="late",
            activity=ValueInput(state="value", value="late"),
            evidence=(_citation(),),
        )
    )
    assert not late.ok


def test_tool_catalog_is_exactly_typed_and_has_no_generic_patch_tool() -> None:
    definitions = get_tool_definitions()
    names = [item.name for item in definitions]
    assert names == [
        "inspect_interview_state",
        "record_process_step",
        "connect_process_steps",
        "record_resource_usage",
        "record_issue",
        "revise_record",
        "complete_interview",
    ]
    schemas = tool_schemas()
    encoded = json.dumps(schemas, ensure_ascii=False, sort_keys=True)
    assert "record_fact" not in encoded
    assert "JSON Patch" not in encoded
    assert "register_utterance" not in encoded
    assert "EvidenceCitation" in encoded


def test_three_replays_use_the_same_update_path_and_round_trip_json() -> None:
    results = [replay_case_file(path) for path in sorted(CASE_DIR.glob("*.json"))]
    assert {result.case.source_kind for result in results} == {
        "existing_public_fixture",
        "synthetic_partial",
        "synthetic_human",
    }
    assert all(all(receipt.ok for receipt in result.receipts) for result in results)
    for result in results:
        restored = InterviewState.model_validate_json(
            json.dumps(result.state.model_dump(mode="json"), ensure_ascii=False)
        )
        assert restored == result.state
    normal = next(item for item in results if item.case.case_id == "normal_existing")
    partial = next(item for item in results if item.case.case_id == "partial_synthetic")
    human = next(item for item in results if item.case.case_id == "human_synthetic")
    assert normal.state.completion.unresolved_question_ids
    assert partial.state.completion.content_completeness == "incomplete"
    assert any(item.supersedes for item in human.state.claims)
    assert human.state.contradictions[0].status == "resolved"
    assert any(
        item.crud == "unknown" for item in human.state.business_model.data_operations
    )
