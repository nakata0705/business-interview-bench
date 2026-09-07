"""Contract tests for the first InterviewState/tool vertical slice."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

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
    CrudInput,
    DataListInput,
    EntityInput,
    InterviewToolExecutor,
    RecordProcessStepInput,
    RecordResourceUsageInput,
    ReviseRecordInput,
    RevisionChange,
    SystemInput,
    ValueInput,
    get_tool_definitions,
    parse_tool_input,
    tool_schemas,
)
from business_interview.prototype import replay_case_file
from business_interview_bench.interview_agent import _resolve_agent_arguments

# pyright: reportMissingImports=false

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CASE_DIR = PROJECT_ROOT / "examples" / "interview_state" / "cases"
PHASE25_ARTIFACT_DIR = PROJECT_ROOT / "experiments" / "phase25" / "after-schema"


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


def test_phase25_failed_revision_replays_without_model_claim_id() -> None:
    invocations = json.loads(
        (PHASE25_ARTIFACT_DIR / "invocations.json").read_text(encoding="utf-8")
    )
    saved = next(
        item
        for item in invocations
        if item["utterance_id"] == "u2"
        and item["tool_name"] == "revise_record"
        and item["arguments"]["change"]["field"] == "actor"
    )
    arguments = dict(saved["arguments"])
    arguments.pop("replacement_id")

    state = InterviewState.model_validate_json(
        (PHASE25_ARTIFACT_DIR / "state-u1.json").read_text(encoding="utf-8")
    )
    harness = InterviewHarness(state)
    harness.register_utterance(
        Utterance(
            id="u2", speaker="stakeholder", text="その確認を担当するのは経理です。"
        )
    )
    executor = InterviewToolExecutor(harness)
    resolved = _resolve_agent_arguments("revise_record", arguments, harness)
    request = cast(ReviseRecordInput, parse_tool_input("revise_record", resolved))
    receipt = executor.revise_record(request)

    assert receipt.ok
    assert receipt.revised_from == ()
    assert len(receipt.claim_ids) == 1
    assert receipt.claim_ids[0].startswith("claim:step:check_application:actor")
    assert receipt.claim_ids[0] not in {item.id for item in state.claims}
    assert executor.state.business_model.process_steps[0].actor.entity_id == (
        "actor:accounting"
    )
    assert executor.state.claims[0].predicate == "activity"
    assert len({item.id for item in executor.state.claims}) == 2


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
            record_id="usage1",
            change=cast(
                RevisionChange, {"field": "crud", "value": CrudInput(operation="read")}
            ),
            statement="The tracker is read during review.",
            correction_note="The stakeholder corrected the CRUD description.",
            evidence=(_citation(),),
            claim_status="confirmed",
        )
    )
    assert revised.ok
    old = next(item for item in executor.state.claims if item.id == usage.claim_ids[0])
    current = next(
        item for item in executor.state.claims if item.id == revised.claim_ids[0]
    )
    assert old.status == "rejected"
    assert current.supersedes == old.id
    assert current.evidence[0].quote == old.evidence[0].quote
    assert executor.state.business_model.data_operations[0].crud == "read"
    assert all(
        operation.crud != "unknown"
        for operation in executor.state.business_model.data_operations
    )


def test_existing_revision_paths_remain_typed() -> None:
    harness = _harness()
    executor = InterviewToolExecutor(harness)
    _step(executor)
    second_step = executor.record_process_step(
        RecordProcessStepInput(
            step_id="step2",
            activity=ValueInput(state="value", value="archive request"),
            evidence=(_citation(),),
        )
    )
    assert second_step.ok

    activity = executor.revise_record(
        ReviseRecordInput(
            record_id="step1",
            change=cast(
                RevisionChange,
                {
                    "field": "activity",
                    "value": ValueInput(
                        state="value", value="review submitted request"
                    ),
                },
            ),
            statement="The step reviews the submitted request.",
            correction_note="The activity wording was corrected.",
            evidence=(_citation(),),
        )
    )
    assert activity.ok

    flow = executor.connect_process_steps(
        ConnectProcessStepsInput(
            flow_id="flow1",
            from_step_id="SOURCE",
            to_step_id="step1",
            kind="source_boundary",
            condition=ValueInput(state="value", value="request received"),
            evidence=(_citation(),),
        )
    )
    assert flow.ok
    condition = executor.revise_record(
        ReviseRecordInput(
            record_id="flow1",
            change=cast(
                RevisionChange,
                {
                    "field": "condition",
                    "value": ValueInput(state="value", value="request complete"),
                },
            ),
            statement="The boundary applies when the request is complete.",
            correction_note="The flow condition was corrected.",
            evidence=(_citation(),),
        )
    )
    assert condition.ok

    usage = executor.record_resource_usage(
        RecordResourceUsageInput(
            usage_id="usage1",
            process_step_id="step1",
            system=SystemInput(id="tracker", label="tracker"),
            data_type=EntityInput(id="request", label="request"),
            crud="unknown",
            evidence=(_citation(),),
        )
    )
    assert usage.ok
    system = executor.revise_record(
        ReviseRecordInput(
            record_id="usage1",
            change=cast(
                RevisionChange,
                {
                    "field": "system",
                    "value": SystemInput(id="archive", label="archive"),
                },
            ),
            statement="The usage is in the archive system.",
            correction_note="The system was clarified.",
            evidence=(_citation(),),
        )
    )
    data_type = executor.revise_record(
        ReviseRecordInput(
            record_id="usage1",
            change=cast(
                RevisionChange,
                {
                    "field": "data_type",
                    "value": EntityInput(
                        id="archived_request", label="archived request"
                    ),
                },
            ),
            statement="The usage handles the archived request.",
            correction_note="The data type was clarified.",
            evidence=(_citation(),),
        )
    )
    assert system.ok and data_type.ok
    operation = executor.state.business_model.data_operations[0]
    assert operation.system.entity_id == "archive"
    assert operation.data_type.entity_id == "archived_request"
    assert operation.crud == "unknown"
    assert executor.state.business_model.flows[0].condition.value == "request complete"
    assert executor.state.business_model.process_steps[0].activity.value == (
        "review submitted request"
    )


def test_incremental_process_fields_add_and_correct_in_conversation_order() -> None:
    harness = InterviewHarness()
    executor = InterviewToolExecutor(harness)

    def turn(utterance_id: str, text: str) -> EvidenceCitation:
        harness.register_utterance(
            Utterance(id=utterance_id, speaker="stakeholder", text=text)
        )
        return EvidenceCitation(
            utterance_id=utterance_id,
            start=0,
            end=len(text),
            quote=text,
            semantic_support="supports",
        )

    first_citation = turn("u1", "まず申請内容を確認します")
    first = executor.record_process_step(
        RecordProcessStepInput(
            step_id="review",
            activity=ValueInput(state="value", value="申請内容を確認"),
            evidence=(first_citation,),
        )
    )
    assert first.ok
    assert executor.state.business_model.process_steps[0].actor.state == "unset"
    assert executor.state.business_model.process_steps[0].inputs.state == "unset"
    assert executor.state.business_model.process_steps[0].outputs.state == "unset"

    second_citation = turn("u2", "担当は経理で、申請書を確認します")
    actor = executor.revise_record(
        ReviseRecordInput(
            record_id="review",
            change=cast(
                RevisionChange,
                {
                    "field": "actor",
                    "value": EntityInput(id="accounting", label="経理"),
                },
            ),
            statement="reviewの担当は経理です。",
            correction_note="追加回答で担当者が判明した。",
            evidence=(second_citation,),
            claim_status="confirmed",
        )
    )
    inputs = executor.revise_record(
        ReviseRecordInput(
            record_id="review",
            change=cast(
                RevisionChange,
                {
                    "field": "inputs",
                    "value": DataListInput(
                        state="value",
                        items=(EntityInput(id="application", label="申請書"),),
                    ),
                },
            ),
            statement="reviewの入力は申請書です。",
            correction_note="追加回答で入力データが判明した。",
            evidence=(second_citation,),
            claim_status="confirmed",
        )
    )
    assert actor.ok and inputs.ok
    assert actor.revised_from == ()
    assert set(actor.created_entity_ids) == {"accounting"}
    assert set(inputs.created_entity_ids) == {"application"}

    third_citation = turn("u3", "確認後は確認結果を残します")
    outputs = executor.revise_record(
        ReviseRecordInput(
            record_id="review",
            change=cast(
                RevisionChange,
                {
                    "field": "outputs",
                    "value": DataListInput(
                        state="value",
                        items=(EntityInput(id="review_result", label="確認結果"),),
                    ),
                },
            ),
            statement="reviewの出力は確認結果です。",
            correction_note="追加回答で出力データが判明した。",
            evidence=(third_citation,),
            claim_status="confirmed",
        )
    )
    assert outputs.ok
    step = executor.state.business_model.process_steps[0]
    assert step.actor.entity_id == "accounting"
    assert step.inputs.entity_ids == ("application",)
    assert step.outputs.entity_ids == ("review_result",)

    fourth_citation = turn("u4", "すみません、担当は経理ではなく営業です")
    correction = executor.revise_record(
        ReviseRecordInput(
            record_id="review",
            change=cast(
                RevisionChange,
                {"field": "actor", "value": EntityInput(id="sales", label="営業")},
            ),
            statement="reviewの担当は営業です。",
            correction_note="訂正回答で担当者が営業だと判明した。",
            evidence=(fourth_citation,),
            claim_status="confirmed",
        )
    )
    assert correction.ok
    assert correction.revised_from == (actor.claim_ids[0],)
    assert correction.created_entity_ids == ("sales",)
    step = executor.state.business_model.process_steps[0]
    assert len(executor.state.business_model.process_steps) == 1
    assert step.actor.entity_id == "sales"
    assert step.inputs.entity_ids == ("application",)
    assert step.outputs.entity_ids == ("review_result",)

    old_actor = next(
        item for item in executor.state.claims if item.id == actor.claim_ids[0]
    )
    current_actor = next(
        item for item in executor.state.claims if item.id == correction.claim_ids[0]
    )
    assert old_actor.status == "rejected"
    assert old_actor.evidence[0].utterance_id == "u2"
    assert current_actor.supersedes == old_actor.id
    assert current_actor.evidence[0].utterance_id == "u4"
    assert current_actor.change_reason == "訂正回答で担当者が営業だと判明した。"

    before_stale_update = executor.state.model_dump(mode="json")
    stale = executor.revise_record(
        ReviseRecordInput(
            record_id="review",
            change=cast(
                RevisionChange,
                {"field": "actor", "value": EntityInput(id="accounting")},
            ),
            expected_claim_id=actor.claim_ids[0],
            statement="The stale owner claim is used.",
            correction_note="stale claim must be rejected",
            evidence=(fourth_citation,),
        )
    )
    assert not stale.ok
    assert executor.state.model_dump(mode="json") == before_stale_update

    restored = InterviewState.model_validate_json(
        json.dumps(executor.state.model_dump(mode="json"), ensure_ascii=False)
    )
    continued_harness = InterviewHarness(restored)
    continued_harness.register_utterance(
        Utterance(id="u5", speaker="stakeholder", text="入力は申請書だけです")
    )
    continued = InterviewToolExecutor(continued_harness).revise_record(
        ReviseRecordInput(
            record_id="review",
            change=cast(
                RevisionChange,
                {
                    "field": "inputs",
                    "value": DataListInput(
                        state="value", items=(EntityInput(id="application"),)
                    ),
                },
            ),
            statement="reviewの入力は既存の申請書です。",
            correction_note="保存後の追回答で入力を確認した。",
            evidence=(
                EvidenceCitation(
                    utterance_id="u5",
                    start=0,
                    end=10,
                    quote="入力は申請書だけです",
                    semantic_support="supports",
                ),
            ),
        )
    )
    assert continued.ok
    assert continued.created_entity_ids == ()
    assert continued.reused_entity_ids == ("application",)


def test_generated_revision_ids_survive_state_round_trip_and_rejected_history() -> None:
    harness = _harness("The coordinator reviews the request.")
    executor = InterviewToolExecutor(harness)
    created = executor.record_process_step(
        RecordProcessStepInput(
            step_id="review",
            activity=ValueInput(state="value", value="review request"),
            evidence=(_citation("The coordinator reviews the request."),),
        )
    )
    assert created.ok

    first = executor.revise_record(
        ReviseRecordInput(
            record_id="review",
            change=cast(
                RevisionChange,
                {
                    "field": "actor",
                    "value": EntityInput(id="accounting", label="accounting"),
                },
            ),
            statement="The owner is accounting.",
            correction_note="The owner became known.",
            evidence=(_citation("The coordinator reviews the request."),),
        )
    )
    assert first.ok

    second = executor.revise_record(
        ReviseRecordInput(
            record_id="review",
            change=cast(
                RevisionChange,
                {
                    "field": "actor",
                    "value": EntityInput(id="sales", label="sales"),
                },
            ),
            expected_claim_id=first.claim_ids[0],
            statement="The owner is sales.",
            correction_note="The owner was corrected.",
            evidence=(_citation("The coordinator reviews the request."),),
        )
    )
    assert second.ok
    first_id = first.claim_ids[0]
    second_id = second.claim_ids[0]
    assert first_id != second_id
    assert second.revised_from == (first_id,)

    restored = InterviewState.model_validate_json(
        json.dumps(executor.state.model_dump(mode="json"), ensure_ascii=False)
    )
    continued = InterviewToolExecutor(InterviewHarness(restored)).revise_record(
        ReviseRecordInput(
            record_id="review",
            change=cast(
                RevisionChange,
                {
                    "field": "actor",
                    "value": EntityInput(id="general_affairs", label="general affairs"),
                },
            ),
            expected_claim_id=second_id,
            statement="The owner is general affairs.",
            correction_note="The owner was corrected again after restore.",
            evidence=(_citation("The coordinator reviews the request."),),
        )
    )
    assert continued.ok
    third_id = continued.claim_ids[0]
    assert third_id not in {item.id for item in restored.claims}
    assert continued.revised_from == (second_id,)
    assert len({item.id for item in restored.claims} | {third_id}) == 4


def test_dont_know_fields_can_become_typed_values() -> None:
    harness = _harness()
    executor = InterviewToolExecutor(harness)
    initial = executor.record_process_step(
        RecordProcessStepInput(
            step_id="review",
            activity=ValueInput(state="value", value="review"),
            actor=EntityInput(state="dont_know"),
            inputs=DataListInput(state="dont_know"),
            outputs=DataListInput(state="absent"),
            evidence=(_citation(),),
        )
    )
    assert initial.ok
    actor = executor.revise_record(
        ReviseRecordInput(
            record_id="review",
            change=cast(
                RevisionChange,
                {
                    "field": "actor",
                    "value": EntityInput(id="actor1", label="coordinator"),
                },
            ),
            statement="The review owner is the coordinator.",
            correction_note="The owner became known.",
            evidence=(_citation(),),
        )
    )
    inputs = executor.revise_record(
        ReviseRecordInput(
            record_id="review",
            change=cast(
                RevisionChange,
                {
                    "field": "inputs",
                    "value": DataListInput(
                        state="value", items=(EntityInput(id="data1", label="request"),)
                    ),
                },
            ),
            statement="The review input is the request.",
            correction_note="The input became known.",
            evidence=(_citation(),),
        )
    )
    assert actor.ok and inputs.ok
    initial_actor_claim_id = next(
        claim_id for claim_id in initial.claim_ids if claim_id.endswith(":actor")
    )
    initial_inputs_claim_id = next(
        claim_id for claim_id in initial.claim_ids if claim_id.endswith(":inputs")
    )
    assert actor.revised_from == (initial_actor_claim_id,)
    assert inputs.revised_from == (initial_inputs_claim_id,)
    assert executor.state.business_model.process_steps[0].actor.entity_id == "actor1"
    assert executor.state.business_model.process_steps[0].inputs.entity_ids == (
        "data1",
    )
    assert executor.state.business_model.process_steps[0].outputs.state == "absent"


def test_failed_incremental_update_does_not_partially_create_entities() -> None:
    harness = _harness()
    executor = InterviewToolExecutor(harness)
    created = executor.record_process_step(
        RecordProcessStepInput(
            step_id="review",
            activity=ValueInput(state="value", value="review"),
            actor=EntityInput(id="accounting", label="accounting"),
            evidence=(_citation(),),
        )
    )
    assert created.ok
    before = executor.state.model_dump(mode="json")

    invalid_quote = executor.revise_record(
        ReviseRecordInput(
            record_id="review",
            change=cast(
                RevisionChange,
                {"field": "actor", "value": EntityInput(id="sales", label="sales")},
            ),
            statement="The owner is sales.",
            correction_note="bad citation",
            evidence=(
                EvidenceCitation(utterance_id="u1", start=0, end=3, quote="wrong"),
            ),
        )
    )
    assert not invalid_quote.ok
    assert executor.state.model_dump(mode="json") == before
    assert not any(item.id == "sales" for item in executor.state.business_model.actors)

    label_conflict = executor.revise_record(
        ReviseRecordInput(
            record_id="review",
            change=cast(
                RevisionChange,
                {"field": "actor", "value": EntityInput(id="accounting", label="別名")},
            ),
            statement="The owner is accounting.",
            correction_note="conflicting label",
            evidence=(_citation(),),
        )
    )
    assert not label_conflict.ok
    assert executor.state.model_dump(mode="json") == before


def test_rejected_revision_does_not_change_the_current_projection() -> None:
    harness = _harness()
    executor = InterviewToolExecutor(harness)
    _step(executor)
    rejected = executor.revise_record(
        ReviseRecordInput(
            record_id="step1",
            change=cast(
                RevisionChange,
                {"field": "actor", "value": EntityInput(id="sales", label="sales")},
            ),
            statement="The owner might be sales.",
            correction_note="The candidate value was rejected.",
            evidence=(_citation(),),
            claim_status="rejected",
        )
    )
    assert rejected.ok
    assert rejected.revised_from == ()
    assert rejected.created_entity_ids == ()
    assert executor.state.business_model.process_steps[0].actor.entity_id == "actor1"
    assert not any(item.id == "sales" for item in executor.state.business_model.actors)
    candidate = next(
        item for item in executor.state.claims if item.id == rejected.claim_ids[0]
    )
    assert candidate.status == "rejected"
    assert candidate.supersedes is None


def test_revise_record_schema_parses_field_specific_typed_values() -> None:
    parsed = parse_tool_input(
        "revise_record",
        {
            "record_id": "review",
            "change": {
                "field": "inputs",
                "value": {
                    "state": "value",
                    "items": [{"id": "request", "label": "request"}],
                },
            },
            "statement": "The input is the request.",
            "correction_note": "The input was identified.",
            "evidence": [],
        },
    )
    assert isinstance(parsed, ReviseRecordInput)
    assert parsed.change.field == "inputs"
    assert isinstance(parsed.change.value, DataListInput)
    assert parsed.change.value.items[0].id == "request"

    legacy_arguments = parsed.model_dump(mode="python")
    legacy_arguments["replacement_id"] = "claim:legacy"
    with pytest.raises(ValueError, match="extra"):
        parse_tool_input("revise_record", legacy_arguments)

    revise_schema = tool_schemas()["revise_record"]
    assert "field" not in revise_schema["properties"]
    assert "value" not in revise_schema["properties"]
    change_schema = revise_schema["properties"]["change"]
    assert len(change_schema["anyOf"]) == 8
    assert (
        revise_schema["$defs"]["ActorChange"]["properties"]["value"]["$ref"]
        == "#/$defs/EntityInput"
    )
    assert (
        revise_schema["$defs"]["SystemChange"]["properties"]["value"]["$ref"]
        == "#/$defs/SystemInput"
    )
    with pytest.raises(ValueError, match="extra"):
        parse_tool_input(
            "revise_record",
            {
                "record_id": "review",
                "change": {
                    "field": "actor",
                    "value": {
                        "id": "actor:accounting",
                        "label": "経理",
                        "kind": "named",
                    },
                },
                "statement": "The owner is accounting.",
                "correction_note": "Wrong entity shape.",
                "evidence": [],
            },
        )
    with pytest.raises(ValueError, match="field"):
        ReviseRecordInput(
            record_id="review",
            change=cast(
                RevisionChange,
                {
                    "field": "actor",
                    "value": DataListInput(
                        state="value",
                        items=(EntityInput(id="request", label="request"),),
                    ),
                },
            ),
            statement="The owner is known.",
            correction_note="wrong type",
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


def test_replays_use_the_same_update_path_and_round_trip_json() -> None:
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
    incremental = next(
        item for item in results if item.case.case_id == "incremental_synthetic"
    )
    assert normal.state.completion.unresolved_question_ids
    assert partial.state.completion.content_completeness == "incomplete"
    assert any(item.supersedes for item in human.state.claims)
    assert human.state.contradictions[0].status == "resolved"
    assert any(
        item.crud == "unknown" for item in human.state.business_model.data_operations
    )
    assert len(incremental.receipts) == 5
    assert len(incremental.state.business_model.process_steps) == 1
    incremental_step = incremental.state.business_model.process_steps[0]
    assert incremental_step.id == "review"
    assert incremental_step.actor.entity_id == "sales"
    assert incremental_step.inputs.entity_ids == ("application",)
    assert incremental_step.outputs.entity_ids == ("review_result",)
    assert incremental.receipts[-1].revised_from == (
        incremental.receipts[1].claim_ids[0],
    )
