"""Typed seven-operation boundary for the minimal InterviewState prototype.

The input models are the source for the agent JSON Schemas.  There is no
``record_fact`` catch-all and no arbitrary JSON Patch operation.  Utterance
registration and evidence-ID issuance remain methods of ``InterviewHarness``;
neither appears in ``get_tool_definitions``.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .interview_state import (
    SINK_ENDPOINT,
    SOURCE_ENDPOINT,
    ActorRecord,
    BusinessModel,
    Claim,
    ClaimStatus,
    Completion,
    Contradiction,
    CrudOperation,
    DataOperation,
    DataTypeRecord,
    EntityLink,
    EntityList,
    EvidenceCitation,
    EvidenceRef,
    FlowKind,
    InformationState,
    InformationValue,
    InterviewHarness,
    InterviewState,
    InterviewStateError,
    Issue,
    IssueKind,
    OpenQuestion,
    ProcessFlow,
    ProcessStep,
    SystemRecord,
)

ToolName = Literal[
    "inspect_interview_state",
    "record_process_step",
    "connect_process_steps",
    "record_resource_usage",
    "record_issue",
    "revise_record",
    "complete_interview",
]


class ValueInput(BaseModel):
    """Typed tool input for a scalar that may be unset, absent, or unknown."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    state: InformationState = "unset"
    value: str | None = None

    @model_validator(mode="after")
    def _matches_state(self) -> ValueInput:
        if self.state == "value" and (self.value is None or not self.value.strip()):
            raise ValueError("value state requires a non-empty value")
        if self.state != "value" and self.value is not None:
            raise ValueError("non-value state must not carry a value")
        return self


class EntityInput(BaseModel):
    """Create or reuse a local actor/data entity, or state why it is unknown."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    state: Literal["value", "absent", "dont_know"] = "value"
    id: str | None = None
    label: str | None = None

    @model_validator(mode="after")
    def _matches_state(self) -> EntityInput:
        if self.state == "value":
            if self.id is None or not self.id.strip():
                raise ValueError("value entity requires id")
        elif self.id is not None or self.label is not None:
            raise ValueError("non-value entity must not carry id or label")
        return self


class SystemInput(EntityInput):
    kind: Literal["named", "manual"] = "named"

    @model_validator(mode="after")
    def _manual_is_named(self) -> SystemInput:
        if self.state != "value" and self.kind != "named":
            raise ValueError("non-value system cannot be manual")
        return self


class DataListInput(BaseModel):
    """Inputs/outputs of a step with an explicit empty/unknown distinction."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    state: InformationState = "unset"
    items: tuple[EntityInput, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _matches_state(self) -> DataListInput:
        if self.state == "value":
            if not self.items:
                raise ValueError("value data list requires at least one item")
            if any(item.state != "value" for item in self.items):
                raise ValueError("value data list items must be value entities")
        elif self.items:
            raise ValueError("non-value data list must not carry items")
        return self


class InspectInterviewStateInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    target_ids: tuple[str, ...] = Field(default_factory=tuple)
    include_evidence: bool = True


class RecordProcessStepInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    step_id: str = Field(min_length=1)
    activity: ValueInput
    actor: EntityInput | None = None
    inputs: DataListInput = Field(default_factory=DataListInput)
    outputs: DataListInput = Field(default_factory=DataListInput)
    evidence: tuple[EvidenceCitation, ...] = Field(default_factory=tuple)
    claim_status: ClaimStatus = "provisional"


class ConnectProcessStepsInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    flow_id: str = Field(min_length=1)
    from_step_id: str = Field(min_length=1)
    to_step_id: str = Field(min_length=1)
    kind: FlowKind = "normal"
    condition: ValueInput = Field(default_factory=ValueInput)
    evidence: tuple[EvidenceCitation, ...] = Field(default_factory=tuple)
    claim_status: ClaimStatus = "provisional"


class RecordResourceUsageInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    usage_id: str = Field(min_length=1)
    process_step_id: str = Field(min_length=1)
    system: SystemInput
    data_type: EntityInput
    crud: CrudOperation
    evidence: tuple[EvidenceCitation, ...] = Field(default_factory=tuple)
    claim_status: ClaimStatus = "provisional"


class RecordIssueInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    issue_id: str = Field(min_length=1)
    kind: IssueKind
    information_state: InformationState = "unset"
    description: str = Field(min_length=1)
    target_ids: tuple[str, ...] = Field(default_factory=tuple)
    claim_ids: tuple[str, ...] = Field(default_factory=tuple)
    question: str | None = None
    contradiction_status: Literal["open", "resolved"] = "open"
    resolution_claim_id: str | None = None
    evidence: tuple[EvidenceCitation, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _contradiction_resolution(self) -> RecordIssueInput:
        if self.kind != "contradiction" and (
            self.contradiction_status != "open" or self.resolution_claim_id is not None
        ):
            raise ValueError(
                "contradiction resolution fields are only valid for contradictions"
            )
        if self.contradiction_status == "resolved" and not self.resolution_claim_id:
            raise ValueError("resolved contradiction requires resolution_claim_id")
        return self


class ReviseRecordInput(BaseModel):
    """A typed claim revision; it is not an arbitrary record patch."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    record_id: str = Field(min_length=1)
    replacement_id: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    value: ValueInput
    correction_note: str = Field(min_length=1)
    evidence: tuple[EvidenceCitation, ...] = Field(default_factory=tuple)
    claim_status: ClaimStatus = "provisional"


class CompleteInterviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    termination_reason: str = Field(min_length=1)
    unresolved_question_ids: tuple[str, ...] | None = None
    stakeholder_confirmed: bool = False
    confirmation_evidence: tuple[EvidenceCitation, ...] = Field(default_factory=tuple)
    content_completeness: Literal["unknown", "complete", "incomplete"] = "unknown"

    @model_validator(mode="after")
    def _confirmation_has_citation(self) -> CompleteInterviewInput:
        if self.stakeholder_confirmed and not self.confirmation_evidence:
            raise ValueError("stakeholder_confirmed requires confirmation_evidence")
        if not self.stakeholder_confirmed and self.confirmation_evidence:
            raise ValueError(
                "confirmation_evidence requires stakeholder_confirmed=true"
            )
        return self


class ToolError(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    fields: tuple[str, ...] = Field(default_factory=tuple)


class InspectionSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    business_model: BusinessModel
    current_claims: tuple[Claim, ...]
    related_evidence: tuple[EvidenceRef, ...]
    open_questions: tuple[OpenQuestion, ...]
    contradictions: tuple[Contradiction, ...]


class ToolOutput(BaseModel):
    """Common typed receipt returned by every operation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    operation: ToolName
    ok: bool
    updated_ids: tuple[str, ...] = Field(default_factory=tuple)
    claim_ids: tuple[str, ...] = Field(default_factory=tuple)
    question_ids: tuple[str, ...] = Field(default_factory=tuple)
    contradiction_ids: tuple[str, ...] = Field(default_factory=tuple)
    revised_from: tuple[str, ...] = Field(default_factory=tuple)
    errors: tuple[ToolError, ...] = Field(default_factory=tuple)
    snapshot: InspectionSnapshot | None = None
    completion: Completion | None = None


class ToolDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: ToolName
    description: str = Field(min_length=1)
    input_schema: dict[str, Any]


class InterviewToolExecutor:
    """Execute the seven operations against one harness-owned state.

    The executor never registers utterances.  It only asks the harness to
    resolve citations into already validated ``EvidenceRef`` objects, builds a
    candidate state, and swaps it in after Pydantic validation succeeds.
    """

    def __init__(self, harness: InterviewHarness) -> None:
        self.harness = harness

    @property
    def state(self) -> InterviewState:
        return self.harness.state

    def inspect_interview_state(
        self, request: InspectInterviewStateInput
    ) -> ToolOutput:
        target_ids = set(request.target_ids)
        claims = tuple(
            item
            for item in self.state.active_claims()
            if not target_ids or item.target_id in target_ids
        )
        questions = tuple(
            item
            for item in self.state.open_questions
            if not target_ids or target_ids.intersection(item.target_ids)
        )
        contradictions = tuple(
            item
            for item in self.state.contradictions
            if not target_ids
            or any(
                claim_id in {claim.id for claim in claims}
                for claim_id in item.claim_ids
            )
        )
        evidence: tuple[EvidenceRef, ...] = ()
        if request.include_evidence:
            seen: set[str] = set()
            collected: list[EvidenceRef] = []
            for claim in claims:
                for item in claim.evidence:
                    if item.evidence_id not in seen:
                        seen.add(item.evidence_id)
                        collected.append(item)
            evidence = tuple(collected)
        snapshot = InspectionSnapshot(
            business_model=self.state.business_model,
            current_claims=claims,
            related_evidence=evidence,
            open_questions=questions,
            contradictions=contradictions,
        )
        return ToolOutput(
            operation="inspect_interview_state",
            ok=True,
            snapshot=snapshot,
        )

    def record_process_step(self, request: RecordProcessStepInput) -> ToolOutput:
        operation: ToolName = "record_process_step"
        try:
            self._require_active()
            self._require_evidence(request.evidence, operation)
            evidence = self._resolve_evidence(request.evidence)

            def build(state: InterviewState) -> tuple[InterviewState, tuple[str, ...]]:
                model = state.business_model
                if _has_id(model.process_steps, request.step_id):
                    raise InterviewStateError(
                        f"process step ID already exists: {request.step_id!r}"
                    )
                actors, actor_link = _ensure_actor(model.actors, request.actor)
                data_types = model.data_types
                data_types, inputs = _ensure_data_list(data_types, request.inputs)
                data_types, outputs = _ensure_data_list(data_types, request.outputs)
                step = ProcessStep(
                    id=request.step_id,
                    activity=InformationValue.model_validate(
                        request.activity.model_dump()
                    ),
                    actor=actor_link,
                    inputs=inputs,
                    outputs=outputs,
                )
                updated_model = model.model_copy(
                    update={
                        "actors": actors,
                        "data_types": data_types,
                        "process_steps": (*model.process_steps, step),
                    }
                )
                claims = _step_claims(request, evidence)
                updated = state.model_copy(
                    update={
                        "business_model": updated_model,
                        "claims": (*state.claims, *claims),
                    }
                )
                return updated, tuple(item.id for item in claims)

            updated, claim_ids = self._commit(build)
            self.harness.state = updated
            return _success(
                operation,
                updated_ids=(request.step_id,),
                claim_ids=claim_ids,
            )
        except (InterviewStateError, ValidationError, ValueError) as exc:
            return _failure(operation, exc)

    def connect_process_steps(self, request: ConnectProcessStepsInput) -> ToolOutput:
        operation: ToolName = "connect_process_steps"
        try:
            self._require_active()
            self._require_evidence(request.evidence, operation)
            evidence = self._resolve_evidence(request.evidence)

            def build(state: InterviewState) -> tuple[InterviewState, tuple[str, ...]]:
                model = state.business_model
                if _has_id(model.flows, request.flow_id):
                    raise InterviewStateError(
                        f"flow ID already exists: {request.flow_id!r}"
                    )
                step_ids = {item.id for item in model.process_steps}
                _validate_flow_endpoints(
                    request.from_step_id,
                    request.to_step_id,
                    request.kind,
                    step_ids,
                )
                flow = ProcessFlow(
                    id=request.flow_id,
                    from_id=request.from_step_id,
                    to_id=request.to_step_id,
                    kind=request.kind,
                    condition=InformationValue.model_validate(
                        request.condition.model_dump()
                    ),
                )
                updated_model = model.model_copy(update={"flows": (*model.flows, flow)})
                claims = _flow_claims(request, evidence)
                updated = state.model_copy(
                    update={
                        "business_model": updated_model,
                        "claims": (*state.claims, *claims),
                    }
                )
                return updated, tuple(item.id for item in claims)

            updated, claim_ids = self._commit(build)
            self.harness.state = updated
            return _success(
                operation,
                updated_ids=(request.flow_id,),
                claim_ids=claim_ids,
            )
        except (InterviewStateError, ValidationError, ValueError) as exc:
            return _failure(operation, exc)

    def record_resource_usage(self, request: RecordResourceUsageInput) -> ToolOutput:
        operation: ToolName = "record_resource_usage"
        try:
            self._require_active()
            self._require_evidence(request.evidence, operation)
            evidence = self._resolve_evidence(request.evidence)

            def build(state: InterviewState) -> tuple[InterviewState, tuple[str, ...]]:
                model = state.business_model
                if _has_id(model.data_operations, request.usage_id):
                    raise InterviewStateError(
                        f"resource usage ID already exists: {request.usage_id!r}"
                    )
                if not _has_id(model.process_steps, request.process_step_id):
                    raise InterviewStateError(
                        f"process step does not exist: {request.process_step_id!r}"
                    )
                systems, system_link = _ensure_system(model.systems, request.system)
                data_types, data_link = _ensure_one_data(
                    model.data_types, request.data_type
                )
                operation_record = DataOperation(
                    id=request.usage_id,
                    process_step_id=request.process_step_id,
                    system=system_link,
                    data_type=data_link,
                    crud=request.crud,
                )
                updated_model = model.model_copy(
                    update={
                        "systems": systems,
                        "data_types": data_types,
                        "data_operations": (
                            *model.data_operations,
                            operation_record,
                        ),
                    }
                )
                claims = _resource_claims(request, system_link, data_link, evidence)
                updated = state.model_copy(
                    update={
                        "business_model": updated_model,
                        "claims": (*state.claims, *claims),
                    }
                )
                return updated, tuple(item.id for item in claims)

            updated, claim_ids = self._commit(build)
            self.harness.state = updated
            return _success(
                operation,
                updated_ids=(request.usage_id,),
                claim_ids=claim_ids,
            )
        except (InterviewStateError, ValidationError, ValueError) as exc:
            return _failure(operation, exc)

    def record_issue(self, request: RecordIssueInput) -> ToolOutput:
        operation: ToolName = "record_issue"
        try:
            self._require_active()
            self._require_evidence(request.evidence, operation)
            evidence = self._resolve_evidence(request.evidence)

            def build(
                state: InterviewState,
            ) -> tuple[InterviewState, tuple[str, ...], tuple[str, ...]]:
                if _has_id(state.issues, request.issue_id):
                    raise InterviewStateError(
                        f"issue ID already exists: {request.issue_id!r}"
                    )
                if not request.target_ids:
                    raise InterviewStateError(
                        "issue requires at least one target record"
                    )
                _validate_target_ids_for_state(state, request.target_ids)
                claims_by_id = {item.id: item for item in state.claims}
                if any(item not in claims_by_id for item in request.claim_ids):
                    raise InterviewStateError("issue contains an unknown claim ID")
                if request.kind == "contradiction" and len(request.claim_ids) < 2:
                    raise InterviewStateError(
                        "contradiction issue requires at least two claim IDs"
                    )
                if (
                    request.resolution_claim_id is not None
                    and request.resolution_claim_id not in claims_by_id
                ):
                    raise InterviewStateError(
                        "contradiction resolution references an unknown claim ID"
                    )
                if request.kind == "unknown" and not request.question:
                    raise InterviewStateError("unknown issue requires a question")
                question_id: str | None = None
                contradiction_id: str | None = None
                questions = state.open_questions
                contradictions = state.contradictions
                if request.kind == "unknown":
                    question_id = f"question:{request.issue_id}"
                    if _has_id(questions, question_id):
                        raise InterviewStateError(
                            f"open question ID already exists: {question_id!r}"
                        )
                    questions = (
                        *questions,
                        OpenQuestion(
                            id=question_id,
                            text=request.question or request.description,
                            target_ids=request.target_ids,
                        ),
                    )
                if request.kind == "contradiction":
                    contradiction_id = f"contradiction:{request.issue_id}"
                    if _has_id(contradictions, contradiction_id):
                        raise InterviewStateError(
                            f"contradiction ID already exists: {contradiction_id!r}"
                        )
                    contradictions = (
                        *contradictions,
                        Contradiction(
                            id=contradiction_id,
                            claim_ids=request.claim_ids,
                            status=request.contradiction_status,
                            resolution_claim_id=request.resolution_claim_id,
                            evidence=evidence,
                        ),
                    )
                issue = Issue(
                    id=request.issue_id,
                    kind=request.kind,
                    information_state=request.information_state,
                    description=request.description,
                    target_ids=request.target_ids,
                    claim_ids=request.claim_ids,
                    evidence=evidence,
                    question_id=question_id,
                    contradiction_id=contradiction_id,
                    status=(
                        request.contradiction_status
                        if request.kind == "contradiction"
                        else "open"
                    ),
                )
                updated = state.model_copy(
                    update={
                        "issues": (*state.issues, issue),
                        "open_questions": questions,
                        "contradictions": contradictions,
                    }
                )
                return (
                    updated,
                    tuple(item for item in (question_id,) if item),
                    tuple(item for item in (contradiction_id,) if item),
                )

            updated, question_ids, contradiction_ids = self._commit_issue(build)
            self.harness.state = updated
            return _success(
                operation,
                updated_ids=(request.issue_id,),
                question_ids=tuple(item for item in question_ids if item),
                contradiction_ids=tuple(item for item in contradiction_ids if item),
            )
        except (InterviewStateError, ValidationError, ValueError) as exc:
            return _failure(operation, exc)

    def revise_record(self, request: ReviseRecordInput) -> ToolOutput:
        operation: ToolName = "revise_record"
        try:
            self._require_active()
            self._require_evidence(request.evidence, operation)
            evidence = self._resolve_evidence(request.evidence)

            def build(state: InterviewState) -> tuple[InterviewState, tuple[str, ...]]:
                old_index = next(
                    (
                        index
                        for index, item in enumerate(state.claims)
                        if item.id == request.record_id
                    ),
                    None,
                )
                if old_index is None:
                    raise InterviewStateError(
                        f"record/claim does not exist: {request.record_id!r}"
                    )
                old = state.claims[old_index]
                if old.status == "rejected":
                    raise InterviewStateError("a rejected claim cannot be revised")
                if any(item.id == request.replacement_id for item in state.claims):
                    raise InterviewStateError(
                        f"replacement claim ID already exists: {request.replacement_id!r}"
                    )
                replacement = Claim(
                    id=request.replacement_id,
                    record_type=old.record_type,
                    target_id=old.target_id,
                    predicate=old.predicate,
                    statement=request.statement,
                    value=InformationValue.model_validate(request.value.model_dump()),
                    evidence=evidence,
                    status=request.claim_status,
                    supersedes=old.id,
                )
                rejected = old.model_copy(update={"status": "rejected"})
                updated_claims = list(state.claims)
                updated_claims[old_index] = rejected
                updated_claims.append(replacement)
                updated_model = _apply_claim_to_model(
                    state.business_model,
                    replacement,
                )
                updated = state.model_copy(
                    update={
                        "business_model": updated_model,
                        "claims": tuple(updated_claims),
                    }
                )
                return updated, (replacement.id,)

            updated, claim_ids = self._commit(build)
            self.harness.state = updated
            return _success(
                operation,
                updated_ids=claim_ids,
                claim_ids=claim_ids,
                revised_from=(request.record_id,),
            )
        except (InterviewStateError, ValidationError, ValueError) as exc:
            return _failure(operation, exc)

    def complete_interview(self, request: CompleteInterviewInput) -> ToolOutput:
        operation: ToolName = "complete_interview"
        try:
            self._require_active()
            if self.state.completion.status != "active":
                raise InterviewStateError("interview is already terminated")
            if request.unresolved_question_ids is None:
                unresolved = tuple(
                    item.id
                    for item in self.state.open_questions
                    if item.status == "open"
                )
            else:
                unresolved = request.unresolved_question_ids
            open_questions = {
                item.id for item in self.state.open_questions if item.status == "open"
            }
            unknown = sorted(set(unresolved) - open_questions)
            if unknown:
                raise InterviewStateError(
                    f"unresolved_question_ids are not open questions: {unknown}"
                )
            if request.stakeholder_confirmed and not any(
                item.semantic_support == "supports"
                for item in request.confirmation_evidence
            ):
                raise InterviewStateError(
                    "stakeholder confirmation requires an evidence citation marked supports"
                )
            confirmation = self._resolve_evidence(request.confirmation_evidence)
            completion = Completion(
                status="ended",
                termination_reason=request.termination_reason.strip(),
                unresolved_question_ids=unresolved,
                stakeholder_confirmed=request.stakeholder_confirmed,
                confirmation_evidence=confirmation,
                content_completeness=request.content_completeness,
            )
            self.harness.state = self.state.model_copy(
                update={"completion": completion}
            )
            return _success(
                operation,
                updated_ids=("completion",),
                completion=completion,
            )
        except (InterviewStateError, ValidationError, ValueError) as exc:
            return _failure(operation, exc)

    def _require_active(self) -> None:
        if self.state.completion.status != "active":
            raise InterviewStateError("interview is terminated; no mutation is allowed")

    @staticmethod
    def _require_evidence(
        citations: Sequence[EvidenceCitation], operation: ToolName
    ) -> None:
        if not citations:
            raise InterviewStateError(
                f"{operation} requires at least one evidence citation"
            )

    def _resolve_evidence(
        self, citations: Sequence[EvidenceCitation]
    ) -> tuple[EvidenceRef, ...]:
        for citation in citations:
            self.harness.validate_citation(citation)
        return tuple(self.harness.issue_evidence(citation) for citation in citations)

    def _commit(
        self,
        builder: Callable[[InterviewState], tuple[InterviewState, tuple[str, ...]]],
    ) -> tuple[InterviewState, tuple[str, ...]]:
        candidate, ids = builder(self.state)
        return InterviewState.model_validate(candidate.model_dump(mode="python")), ids

    def _commit_issue(
        self,
        builder: Callable[
            [InterviewState],
            tuple[InterviewState, tuple[str | None, ...], tuple[str | None, ...]],
        ],
    ) -> tuple[InterviewState, tuple[str | None, ...], tuple[str | None, ...]]:
        candidate, question_ids, contradiction_ids = builder(self.state)
        return (
            InterviewState.model_validate(candidate.model_dump(mode="python")),
            question_ids,
            contradiction_ids,
        )


def _success(
    operation: ToolName,
    *,
    updated_ids: Sequence[str] = (),
    claim_ids: Sequence[str] = (),
    question_ids: Sequence[str] = (),
    contradiction_ids: Sequence[str] = (),
    revised_from: Sequence[str] = (),
    completion: Completion | None = None,
) -> ToolOutput:
    return ToolOutput(
        operation=operation,
        ok=True,
        updated_ids=tuple(updated_ids),
        claim_ids=tuple(claim_ids),
        question_ids=tuple(question_ids),
        contradiction_ids=tuple(contradiction_ids),
        revised_from=tuple(revised_from),
        completion=completion,
    )


def _failure(operation: ToolName, error: Exception) -> ToolOutput:
    message = str(error) or error.__class__.__name__
    return ToolOutput(
        operation=operation,
        ok=False,
        errors=(ToolError(code=error.__class__.__name__, message=message),),
    )


def _has_id(items: Sequence[BaseModel], item_id: str) -> bool:
    return any(getattr(item, "id") == item_id for item in items)


def _ensure_actor(
    actors: tuple[ActorRecord, ...], request: EntityInput | None
) -> tuple[tuple[ActorRecord, ...], EntityLink]:
    if request is None:
        return actors, EntityLink()
    if request.state != "value":
        return actors, EntityLink(state=request.state)
    if request.id is None:
        raise InterviewStateError("value actor requires an ID")
    existing = next((item for item in actors if item.id == request.id), None)
    if existing is not None:
        if request.label is not None and request.label != existing.label:
            raise InterviewStateError(
                f"actor {request.id!r} already has a different label"
            )
        return actors, EntityLink(state="value", entity_id=request.id)
    if request.label is None or not request.label.strip():
        raise InterviewStateError(
            f"label is required when creating actor {request.id!r}"
        )
    return (
        (*actors, ActorRecord(id=request.id, label=request.label)),
        EntityLink(state="value", entity_id=request.id),
    )


def _ensure_data_list(
    data_types: tuple[DataTypeRecord, ...], request: DataListInput
) -> tuple[tuple[DataTypeRecord, ...], EntityList]:
    if request.state != "value":
        return data_types, EntityList(state=request.state)
    current = data_types
    ids: list[str] = []
    for item in request.items:
        if item.id is None:
            raise InterviewStateError("value data type requires an ID")
        current, link = _ensure_one_data(current, item)
        if link.entity_id is None:
            raise InterviewStateError("value data type link requires an ID")
        ids.append(link.entity_id)
    return current, EntityList(state="value", entity_ids=tuple(ids))


def _ensure_one_data(
    data_types: tuple[DataTypeRecord, ...], request: EntityInput
) -> tuple[tuple[DataTypeRecord, ...], EntityLink]:
    if request.state != "value":
        return data_types, EntityLink(state=request.state)
    if request.id is None:
        raise InterviewStateError("value data type requires an ID")
    existing = next((item for item in data_types if item.id == request.id), None)
    if existing is not None:
        if request.label is not None and request.label != existing.label:
            raise InterviewStateError(
                f"data type {request.id!r} already has a different label"
            )
        return data_types, EntityLink(state="value", entity_id=request.id)
    if request.label is None or not request.label.strip():
        raise InterviewStateError(
            f"label is required when creating data type {request.id!r}"
        )
    return (
        (*data_types, DataTypeRecord(id=request.id, label=request.label)),
        EntityLink(state="value", entity_id=request.id),
    )


def _ensure_system(
    systems: tuple[SystemRecord, ...], request: SystemInput
) -> tuple[tuple[SystemRecord, ...], EntityLink]:
    if request.state != "value":
        return systems, EntityLink(state=request.state)
    if request.id is None:
        raise InterviewStateError("value system requires an ID")
    existing = next((item for item in systems if item.id == request.id), None)
    if existing is not None:
        if request.label is not None and request.label != existing.label:
            raise InterviewStateError(
                f"system {request.id!r} already has a different label"
            )
        if existing.kind != request.kind:
            raise InterviewStateError(
                f"system {request.id!r} already has a different kind"
            )
        return systems, EntityLink(state="value", entity_id=request.id)
    if request.label is None or not request.label.strip():
        raise InterviewStateError(
            f"label is required when creating system {request.id!r}"
        )
    return (
        (*systems, SystemRecord(id=request.id, label=request.label, kind=request.kind)),
        EntityLink(state="value", entity_id=request.id),
    )


def _step_claims(
    request: RecordProcessStepInput, evidence: tuple[EvidenceRef, ...]
) -> tuple[Claim, ...]:
    claims = [
        Claim(
            id=f"claim:{request.step_id}:activity",
            record_type="process_step",
            target_id=request.step_id,
            predicate="activity",
            statement=f"Process step {request.step_id} has the recorded activity.",
            value=InformationValue.model_validate(request.activity.model_dump()),
            evidence=evidence,
            status=request.claim_status,
        )
    ]
    if request.actor is not None:
        claims.append(
            Claim(
                id=f"claim:{request.step_id}:actor",
                record_type="process_step",
                target_id=request.step_id,
                predicate="actor",
                statement=f"Process step {request.step_id} has the recorded actor.",
                value=_entity_input_value(request.actor),
                evidence=evidence,
                status=request.claim_status,
            )
        )
    if request.inputs.state != "unset":
        claims.append(
            Claim(
                id=f"claim:{request.step_id}:inputs",
                record_type="process_step",
                target_id=request.step_id,
                predicate="inputs",
                statement=f"Process step {request.step_id} has the recorded inputs.",
                value=_data_list_value(request.inputs),
                evidence=evidence,
                status=request.claim_status,
            )
        )
    if request.outputs.state != "unset":
        claims.append(
            Claim(
                id=f"claim:{request.step_id}:outputs",
                record_type="process_step",
                target_id=request.step_id,
                predicate="outputs",
                statement=f"Process step {request.step_id} has the recorded outputs.",
                value=_data_list_value(request.outputs),
                evidence=evidence,
                status=request.claim_status,
            )
        )
    return tuple(claims)


def _flow_claims(
    request: ConnectProcessStepsInput, evidence: tuple[EvidenceRef, ...]
) -> tuple[Claim, ...]:
    claims = [
        Claim(
            id=f"claim:{request.flow_id}:relation",
            record_type="flow",
            target_id=request.flow_id,
            predicate="relation",
            statement=(
                f"Flow {request.flow_id} connects {request.from_step_id} "
                f"to {request.to_step_id}."
            ),
            value=InformationValue(
                state="value",
                value=f"{request.from_step_id}->{request.to_step_id}",
            ),
            evidence=evidence,
            status=request.claim_status,
        )
    ]
    if request.condition.state != "unset":
        claims.append(
            Claim(
                id=f"claim:{request.flow_id}:condition",
                record_type="flow",
                target_id=request.flow_id,
                predicate="condition",
                statement=f"Flow {request.flow_id} has the recorded condition.",
                value=InformationValue.model_validate(request.condition.model_dump()),
                evidence=evidence,
                status=request.claim_status,
            )
        )
    return tuple(claims)


def _resource_claims(
    request: RecordResourceUsageInput,
    system: EntityLink,
    data_type: EntityLink,
    evidence: tuple[EvidenceRef, ...],
) -> tuple[Claim, ...]:
    return (
        Claim(
            id=f"claim:{request.usage_id}:crud",
            record_type="resource_usage",
            target_id=request.usage_id,
            predicate="crud",
            statement=f"Resource usage {request.usage_id} has the recorded CRUD operation.",
            value=InformationValue(state="value", value=request.crud),
            evidence=evidence,
            status=request.claim_status,
        ),
        Claim(
            id=f"claim:{request.usage_id}:system",
            record_type="resource_usage",
            target_id=request.usage_id,
            predicate="system",
            statement=f"Resource usage {request.usage_id} has the recorded system.",
            value=_link_value(system),
            evidence=evidence,
            status=request.claim_status,
        ),
        Claim(
            id=f"claim:{request.usage_id}:data_type",
            record_type="resource_usage",
            target_id=request.usage_id,
            predicate="data_type",
            statement=f"Resource usage {request.usage_id} has the recorded data type.",
            value=_link_value(data_type),
            evidence=evidence,
            status=request.claim_status,
        ),
    )


def _entity_input_value(request: EntityInput) -> InformationValue:
    return InformationValue(
        state="value" if request.state == "value" else request.state,
        value=request.id if request.state == "value" else None,
    )


def _data_list_value(request: DataListInput) -> InformationValue:
    if request.state != "value":
        return InformationValue(state=request.state)
    return InformationValue(
        state="value",
        value=json.dumps(
            [item.id for item in request.items],
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    )


def _link_value(link: EntityLink) -> InformationValue:
    return InformationValue(
        state=link.state,
        value=link.entity_id if link.state == "value" else None,
    )


def _validate_flow_endpoints(
    from_id: str, to_id: str, kind: FlowKind, step_ids: set[str]
) -> None:
    if from_id not in step_ids and from_id != SOURCE_ENDPOINT:
        raise InterviewStateError(f"from endpoint does not exist: {from_id!r}")
    if to_id not in step_ids and to_id != SINK_ENDPOINT:
        raise InterviewStateError(f"to endpoint does not exist: {to_id!r}")
    if kind == "source_boundary" and (
        from_id != SOURCE_ENDPOINT or to_id == SINK_ENDPOINT
    ):
        raise InterviewStateError("source_boundary must connect SOURCE to a step")
    if kind == "sink_boundary" and (
        to_id != SINK_ENDPOINT or from_id == SOURCE_ENDPOINT
    ):
        raise InterviewStateError("sink_boundary must connect a step to SINK")
    if kind in {"normal", "branch", "exception"} and (
        from_id in {SOURCE_ENDPOINT, SINK_ENDPOINT}
        or to_id in {SOURCE_ENDPOINT, SINK_ENDPOINT}
    ):
        raise InterviewStateError(
            "normal/branch/exception flow cannot use SOURCE or SINK"
        )


def _validate_target_ids_for_state(
    state: InterviewState, target_ids: Sequence[str]
) -> None:
    known = {
        *[
            item.id
            for item in (
                *state.business_model.process_steps,
                *state.business_model.flows,
                *state.business_model.data_operations,
            )
        ],
    }
    unknown = sorted(set(target_ids) - known)
    if unknown:
        raise InterviewStateError(f"issue targets unknown records: {unknown}")


def _apply_claim_to_model(model: BusinessModel, claim: Claim) -> BusinessModel:
    """Apply one typed replacement to the current projection."""
    if claim.record_type == "process_step":
        steps = list(model.process_steps)
        index = next(
            (i for i, item in enumerate(steps) if item.id == claim.target_id), None
        )
        if index is None:
            raise InterviewStateError("revised process step does not exist")
        step = steps[index]
        if claim.predicate == "activity":
            steps[index] = step.model_copy(update={"activity": claim.value})
        elif claim.predicate == "actor":
            steps[index] = step.model_copy(update={"actor": _value_link(claim.value)})
        elif claim.predicate in {"inputs", "outputs"}:
            entity_list = _value_list(claim.value)
            steps[index] = step.model_copy(update={claim.predicate: entity_list})
        else:
            raise InterviewStateError(
                f"process-step predicate is not revisable: {claim.predicate!r}"
            )
        updated = model.model_copy(update={"process_steps": tuple(steps)})
        _validate_model_projection(updated)
        return updated

    if claim.record_type == "flow":
        flows = list(model.flows)
        index = next(
            (i for i, item in enumerate(flows) if item.id == claim.target_id), None
        )
        if index is None:
            raise InterviewStateError("revised flow does not exist")
        if claim.predicate != "condition":
            raise InterviewStateError(
                f"flow predicate is not revisable: {claim.predicate!r}"
            )
        flows[index] = flows[index].model_copy(update={"condition": claim.value})
        updated = model.model_copy(update={"flows": tuple(flows)})
        _validate_model_projection(updated)
        return updated

    operations = list(model.data_operations)
    index = next(
        (i for i, item in enumerate(operations) if item.id == claim.target_id), None
    )
    if index is None:
        raise InterviewStateError("revised resource usage does not exist")
    operation = operations[index]
    if claim.predicate == "crud":
        if claim.value.state != "value" or claim.value.value not in {
            "create",
            "read",
            "update",
            "delete",
            "unknown",
        }:
            raise InterviewStateError(
                "CRUD revision must be one of the five CRUD values"
            )
        operations[index] = operation.model_copy(update={"crud": claim.value.value})
    elif claim.predicate == "system":
        operations[index] = operation.model_copy(
            update={"system": _value_link(claim.value)}
        )
    elif claim.predicate == "data_type":
        operations[index] = operation.model_copy(
            update={"data_type": _value_link(claim.value)}
        )
    else:
        raise InterviewStateError(
            f"resource-usage predicate is not revisable: {claim.predicate!r}"
        )
    updated = model.model_copy(update={"data_operations": tuple(operations)})
    _validate_model_projection(updated)
    return updated


def _value_link(value: InformationValue) -> EntityLink:
    return EntityLink(
        state=value.state, entity_id=value.value if value.state == "value" else None
    )


def _value_list(value: InformationValue) -> EntityList:
    if value.state != "value":
        return EntityList(state=value.state)
    try:
        raw = json.loads(value.value or "")
    except json.JSONDecodeError as exc:
        raise InterviewStateError("revised data list is not valid JSON") from exc
    if not isinstance(raw, list) or not all(
        isinstance(item, str) and item for item in raw
    ):
        raise InterviewStateError("revised data list must contain string IDs")
    return EntityList(state="value", entity_ids=tuple(raw))


def _validate_model_projection(model: BusinessModel) -> None:
    # Reuse the state model's cross-field validation without constructing a
    # temporary state that would require claims for the projection.
    from .interview_state import _validate_business_model

    _validate_business_model(model)


_INPUT_MODELS: dict[ToolName, type[BaseModel]] = {
    "inspect_interview_state": InspectInterviewStateInput,
    "record_process_step": RecordProcessStepInput,
    "connect_process_steps": ConnectProcessStepsInput,
    "record_resource_usage": RecordResourceUsageInput,
    "record_issue": RecordIssueInput,
    "revise_record": ReviseRecordInput,
    "complete_interview": CompleteInterviewInput,
}

_DESCRIPTIONS: dict[ToolName, str] = {
    "inspect_interview_state": "Read the current business understanding, evidence, open questions, and contradictions.",
    "record_process_step": "Record one process step with actor, inputs, outputs, and public evidence.",
    "connect_process_steps": "Record an ordered, conditional, or exception flow between existing steps with evidence.",
    "record_resource_usage": "Link an existing process step to a system and data type with explicit CRUD, including unknown or manual use.",
    "record_issue": "Record an open question, contradiction, exception, or business rule with its target and evidence.",
    "revise_record": "Replace one existing claim while preserving the old rejected claim and its evidence.",
    "complete_interview": "Record termination separately from stakeholder confirmation and content completeness.",
}


def get_tool_definitions() -> tuple[ToolDefinition, ...]:
    """Build agent-facing tool definitions from the Pydantic input models."""
    return tuple(
        ToolDefinition(
            name=name,
            description=_DESCRIPTIONS[name],
            input_schema=model.model_json_schema(),
        )
        for name, model in _INPUT_MODELS.items()
    )


def tool_schemas() -> dict[str, dict[str, Any]]:
    """Return JSON Schemas for the seven operations, generated from Pydantic."""
    return {item.name: item.input_schema for item in get_tool_definitions()}


def parse_tool_input(name: ToolName, payload: object) -> BaseModel:
    """Parse one agent payload with the same Pydantic model used for its schema."""
    return _INPUT_MODELS[name].model_validate(payload)


__all__ = [
    "CompleteInterviewInput",
    "ConnectProcessStepsInput",
    "DataListInput",
    "EntityInput",
    "InspectInterviewStateInput",
    "InspectionSnapshot",
    "InterviewToolExecutor",
    "RecordIssueInput",
    "RecordProcessStepInput",
    "RecordResourceUsageInput",
    "ReviseRecordInput",
    "SystemInput",
    "ToolDefinition",
    "ToolError",
    "ToolName",
    "ToolOutput",
    "ValueInput",
    "get_tool_definitions",
    "parse_tool_input",
    "tool_schemas",
]
