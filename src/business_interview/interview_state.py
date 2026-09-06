"""Minimal public-interview state and typed business-operation tools.

This module is intentionally separate from the historical graph/runtime
contract.  It accepts only a harness-owned utterance ledger and local record
IDs; it does not accept TruthGraph, stakeholder knowledge, WHAT/HOW output, or
an evaluator meaning ID.

The state is immutable at the model boundary.  ``InterviewHarness`` is the
only object that registers public utterances and issues persisted evidence IDs.
The seven operations in :mod:`business_interview.interview_tools` receive
already typed evidence citations and return a new state only after the whole
operation validates successfully.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

InformationState = Literal["unset", "value", "absent", "dont_know"]
ClaimStatus = Literal["provisional", "confirmed", "rejected"]
CrudOperation = Literal["create", "read", "update", "delete", "unknown"]
FlowKind = Literal["normal", "branch", "exception", "source_boundary", "sink_boundary"]
IssueKind = Literal["unknown", "contradiction", "exception", "business_rule"]
IssueStatus = Literal["open", "resolved"]
SemanticSupport = Literal["unassessed", "supports", "contradicts"]
ContentCompleteness = Literal["unknown", "complete", "incomplete"]

SOURCE_ENDPOINT = "SOURCE"
SINK_ENDPOINT = "SINK"
SCHEMA_VERSION = "business_interview.interview_state.v2"


class InterviewStateError(ValueError):
    """Raised when a state or a typed operation violates the prototype contract."""


class Utterance(BaseModel):
    """A harness-registered, immutable public utterance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    speaker: str = Field(min_length=1)
    text: str = Field(min_length=1)


class EvidenceCitation(BaseModel):
    """Agent-supplied citation coordinates before the harness assigns an ID.

    ``start`` is inclusive and ``end`` is exclusive.  Both indexes are Python
    Unicode code-point indexes.  The harness checks the quote against the
    immutable utterance; it does not decide whether the quote semantically
    supports a claim.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    utterance_id: str = Field(min_length=1)
    start: int = Field(ge=0)
    end: int = Field(ge=1)
    quote: str = Field(min_length=1)
    semantic_support: SemanticSupport = "unassessed"

    @model_validator(mode="after")
    def _valid_range(self) -> EvidenceCitation:
        if self.end <= self.start:
            raise ValueError("evidence end must be greater than start")
        return self


class EvidenceRef(EvidenceCitation):
    """Persisted evidence with a harness-issued stable ID."""

    evidence_id: str = Field(min_length=1)


class InformationValue(BaseModel):
    """A four-state scalar value; value and epistemic state are separate axes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    state: InformationState = "unset"
    value: str | None = None

    @model_validator(mode="after")
    def _value_matches_state(self) -> InformationValue:
        if self.state == "value" and (self.value is None or not self.value.strip()):
            raise ValueError("value state requires a non-empty value")
        if self.state != "value" and self.value is not None:
            raise ValueError("non-value state must not carry a value")
        return self


class EntityLink(BaseModel):
    """A reference to an actor/system/data record or an explicit state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    state: InformationState = "unset"
    entity_id: str | None = None

    @model_validator(mode="after")
    def _entity_matches_state(self) -> EntityLink:
        if self.state == "value" and (self.entity_id is None or not self.entity_id):
            raise ValueError("value entity link requires entity_id")
        if self.state != "value" and self.entity_id is not None:
            raise ValueError("non-value entity link must not carry entity_id")
        return self


class EntityList(BaseModel):
    """A four-state list of data-type references."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    state: InformationState = "unset"
    entity_ids: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _entities_match_state(self) -> EntityList:
        if self.state == "value" and not self.entity_ids:
            raise ValueError("value entity list requires at least one entity")
        if self.state != "value" and self.entity_ids:
            raise ValueError("non-value entity list must not carry entity IDs")
        if len(self.entity_ids) != len(set(self.entity_ids)):
            raise ValueError("entity list IDs must be unique")
        return self


class ActorRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    label: str = Field(min_length=1)


class SystemRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    kind: Literal["named", "manual"] = "named"


class DataTypeRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    label: str = Field(min_length=1)


class ProcessStep(BaseModel):
    """Current business-process step projection, distinct from its claims."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    activity: InformationValue
    actor: EntityLink = Field(default_factory=EntityLink)
    inputs: EntityList = Field(default_factory=EntityList)
    outputs: EntityList = Field(default_factory=EntityList)


class ProcessFlow(BaseModel):
    """A flow relation; SOURCE/SINK boundaries have explicit flow kinds."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    from_id: str = Field(min_length=1)
    to_id: str = Field(min_length=1)
    kind: FlowKind = "normal"
    condition: InformationValue = Field(default_factory=InformationValue)


class DataOperation(BaseModel):
    """One process/data/system/CRUD relation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    process_step_id: str = Field(min_length=1)
    system: EntityLink = Field(default_factory=EntityLink)
    data_type: EntityLink = Field(default_factory=EntityLink)
    crud: CrudOperation


class BusinessModel(BaseModel):
    """The current, uniquely readable projection of active business claims."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    actors: tuple[ActorRecord, ...] = Field(default_factory=tuple)
    process_steps: tuple[ProcessStep, ...] = Field(default_factory=tuple)
    flows: tuple[ProcessFlow, ...] = Field(default_factory=tuple)
    systems: tuple[SystemRecord, ...] = Field(default_factory=tuple)
    data_types: tuple[DataTypeRecord, ...] = Field(default_factory=tuple)
    data_operations: tuple[DataOperation, ...] = Field(default_factory=tuple)


class Claim(BaseModel):
    """An evidence-linked assertion or correction-history entry."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    record_type: Literal["process_step", "flow", "resource_usage"]
    target_id: str = Field(min_length=1)
    predicate: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    value: InformationValue
    evidence: tuple[EvidenceRef, ...] = Field(default_factory=tuple)
    status: ClaimStatus = "provisional"
    supersedes: str | None = None
    change_reason: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _confirmed_is_grounded(self) -> Claim:
        if self.status == "confirmed":
            if not self.evidence:
                raise ValueError("confirmed claim requires evidence")
            if not any(item.semantic_support == "supports" for item in self.evidence):
                raise ValueError(
                    "confirmed claim requires an evidence ref marked supports"
                )
        return self


class OpenQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    target_ids: tuple[str, ...] = Field(default_factory=tuple)
    status: IssueStatus = "open"
    resolution_claim_id: str | None = None


class Contradiction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    claim_ids: tuple[str, ...]
    status: IssueStatus = "open"
    resolution_claim_id: str | None = None
    evidence: tuple[EvidenceRef, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _has_multiple_claims(self) -> Contradiction:
        if len(self.claim_ids) < 2:
            raise ValueError("contradiction requires at least two claim IDs")
        if len(self.claim_ids) != len(set(self.claim_ids)):
            raise ValueError("contradiction claim IDs must be unique")
        return self


class Issue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    kind: IssueKind
    information_state: InformationState = "unset"
    description: str = Field(min_length=1)
    target_ids: tuple[str, ...] = Field(default_factory=tuple)
    claim_ids: tuple[str, ...] = Field(default_factory=tuple)
    evidence: tuple[EvidenceRef, ...] = Field(default_factory=tuple)
    question_id: str | None = None
    contradiction_id: str | None = None
    status: IssueStatus = "open"


class Completion(BaseModel):
    """Termination, stakeholder confirmation, and completeness are separate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["active", "ended"] = "active"
    termination_reason: str | None = None
    unresolved_question_ids: tuple[str, ...] = Field(default_factory=tuple)
    stakeholder_confirmed: bool = False
    confirmation_evidence: tuple[EvidenceRef, ...] = Field(default_factory=tuple)
    content_completeness: ContentCompleteness = "unknown"

    @model_validator(mode="after")
    def _terminal_fields(self) -> Completion:
        if self.status == "active":
            if self.termination_reason is not None:
                raise ValueError("active completion cannot have termination_reason")
            if self.unresolved_question_ids:
                raise ValueError("active completion cannot list unresolved questions")
            if self.stakeholder_confirmed or self.confirmation_evidence:
                raise ValueError("active completion cannot contain confirmation")
        else:
            if self.termination_reason is None or not self.termination_reason.strip():
                raise ValueError("ended completion requires termination_reason")
        if self.stakeholder_confirmed and not self.confirmation_evidence:
            raise ValueError("stakeholder_confirmed requires confirmation evidence")
        if not self.stakeholder_confirmed and self.confirmation_evidence:
            raise ValueError("confirmation evidence requires stakeholder_confirmed")
        return self


class InterviewState(BaseModel):
    """The minimal durable state shared by the prototype's seven operations."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["business_interview.interview_state.v2"] = SCHEMA_VERSION
    utterances: tuple[Utterance, ...] = Field(default_factory=tuple)
    claims: tuple[Claim, ...] = Field(default_factory=tuple)
    business_model: BusinessModel = Field(default_factory=BusinessModel)
    open_questions: tuple[OpenQuestion, ...] = Field(default_factory=tuple)
    contradictions: tuple[Contradiction, ...] = Field(default_factory=tuple)
    issues: tuple[Issue, ...] = Field(default_factory=tuple)
    completion: Completion = Field(default_factory=Completion)

    @model_validator(mode="after")
    def _cross_references(self) -> InterviewState:
        _unique_ids(self.utterances, "utterance")
        _unique_ids(self.claims, "claim")
        _unique_ids(self.open_questions, "open question")
        _unique_ids(self.contradictions, "contradiction")
        _unique_ids(self.issues, "issue")
        utterances = {item.id: item for item in self.utterances}
        claims = {item.id: item for item in self.claims}
        record_ids = _record_ids(self.business_model)

        for claim in self.claims:
            if claim.target_id not in record_ids:
                raise ValueError(
                    f"claim {claim.id!r} targets unknown record {claim.target_id!r}"
                )
            if claim.supersedes is not None:
                previous = claims.get(claim.supersedes)
                if previous is None:
                    raise ValueError(
                        f"claim {claim.id!r} supersedes unknown claim "
                        f"{claim.supersedes!r}"
                    )
                if previous.status != "rejected":
                    raise ValueError(
                        f"superseded claim {claim.supersedes!r} must be rejected"
                    )
                if (
                    previous.record_type,
                    previous.target_id,
                    previous.predicate,
                ) != (claim.record_type, claim.target_id, claim.predicate):
                    raise ValueError(
                        f"claim {claim.id!r} supersedes a different record field"
                    )

        for evidence in _all_evidence(self):
            utterance = utterances.get(evidence.utterance_id)
            if utterance is None:
                raise ValueError(
                    f"evidence {evidence.evidence_id!r} references unknown utterance "
                    f"{evidence.utterance_id!r}"
                )
            if evidence.end > len(utterance.text):
                raise ValueError(
                    f"evidence {evidence.evidence_id!r} ends outside utterance "
                    f"{utterance.id!r}"
                )
            if utterance.text[evidence.start : evidence.end] != evidence.quote:
                raise ValueError(
                    f"evidence {evidence.evidence_id!r} quote does not match "
                    f"utterance {utterance.id!r}"
                )

        for question in self.open_questions:
            _validate_target_ids(question.target_ids, record_ids, "open question")
            if (
                question.resolution_claim_id is not None
                and question.resolution_claim_id not in claims
            ):
                raise ValueError(
                    f"open question {question.id!r} has unknown resolution claim"
                )
        for contradiction in self.contradictions:
            if any(claim_id not in claims for claim_id in contradiction.claim_ids):
                raise ValueError(
                    f"contradiction {contradiction.id!r} references an unknown claim"
                )
            if (
                contradiction.resolution_claim_id is not None
                and contradiction.resolution_claim_id not in claims
            ):
                raise ValueError(
                    f"contradiction {contradiction.id!r} has unknown resolution claim"
                )
        for issue in self.issues:
            _validate_target_ids(issue.target_ids, record_ids, "issue")
            if any(claim_id not in claims for claim_id in issue.claim_ids):
                raise ValueError(f"issue {issue.id!r} references an unknown claim")
            if issue.question_id is not None and not any(
                item.id == issue.question_id for item in self.open_questions
            ):
                raise ValueError(f"issue {issue.id!r} has unknown question")
            if issue.contradiction_id is not None and not any(
                item.id == issue.contradiction_id for item in self.contradictions
            ):
                raise ValueError(f"issue {issue.id!r} has unknown contradiction")

        question_by_id = {item.id: item for item in self.open_questions}
        for question_id in self.completion.unresolved_question_ids:
            question = question_by_id.get(question_id)
            if question is None or question.status != "open":
                raise ValueError(
                    f"completion references non-open question {question_id!r}"
                )

        _validate_business_model(self.business_model)
        _validate_active_claims(self.business_model, self.claims)
        return self

    def active_claims(self) -> tuple[Claim, ...]:
        """Return claims still eligible to explain the current projection."""
        return tuple(item for item in self.claims if item.status != "rejected")


class InterviewHarness:
    """Own utterance registration and evidence-ID issuance outside agent tools."""

    def __init__(self, state: InterviewState | None = None) -> None:
        self.state = state or InterviewState()
        self._next_evidence_number = self._existing_evidence_count() + 1

    def register_utterance(self, utterance: Utterance) -> InterviewState:
        """Append an exact public utterance; not exposed in the agent tool catalog."""
        if self.state.completion.status != "active":
            raise InterviewStateError("cannot register an utterance after termination")
        if any(item.id == utterance.id for item in self.state.utterances):
            raise InterviewStateError(f"utterance ID already exists: {utterance.id!r}")
        self.state = self.state.model_copy(
            update={"utterances": (*self.state.utterances, utterance)}
        )
        return self.state

    def validate_citation(self, citation: EvidenceCitation) -> None:
        utterance = next(
            (
                item
                for item in self.state.utterances
                if item.id == citation.utterance_id
            ),
            None,
        )
        if utterance is None:
            raise InterviewStateError(
                f"evidence references unknown utterance {citation.utterance_id!r}"
            )
        if citation.end > len(utterance.text):
            raise InterviewStateError(
                f"evidence range ends outside utterance {utterance.id!r}"
            )
        if utterance.text[citation.start : citation.end] != citation.quote:
            raise InterviewStateError(
                f"evidence quote does not match utterance {utterance.id!r}"
            )

    def prepare_evidence(
        self, citations: Sequence[EvidenceCitation]
    ) -> tuple[EvidenceRef, ...]:
        """Validate citations and prepare IDs without changing the counter."""
        for citation in citations:
            self.validate_citation(citation)
        return tuple(
            EvidenceRef(
                evidence_id=f"ev_{self._next_evidence_number + index:04d}",
                utterance_id=citation.utterance_id,
                start=citation.start,
                end=citation.end,
                quote=citation.quote,
                semantic_support=citation.semantic_support,
            )
            for index, citation in enumerate(citations)
        )

    def commit_evidence(self, count: int) -> None:
        """Advance the harness counter after an operation commits."""
        if count < 0:
            raise InterviewStateError("evidence commit count cannot be negative")
        self._next_evidence_number += count

    def issue_evidence(self, citation: EvidenceCitation) -> EvidenceRef:
        """Validate and issue a persisted ID; this method is harness-only."""
        prepared = self.prepare_evidence((citation,))
        self.commit_evidence(len(prepared))
        return prepared[0]

    def _existing_evidence_count(self) -> int:
        highest = 0
        for evidence in _all_evidence(self.state):
            prefix, separator, number = evidence.evidence_id.rpartition("_")
            if prefix == "ev" and separator and number.isdigit():
                try:
                    highest = max(highest, int(number))
                except ValueError:
                    continue
        return highest


def _unique_ids(items: Iterable[BaseModel], label: str) -> None:
    ids = [getattr(item, "id") for item in items]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{label} IDs must be unique")


def _record_ids(model: BusinessModel) -> set[str]:
    return {
        *[item.id for item in model.process_steps],
        *[item.id for item in model.flows],
        *[item.id for item in model.data_operations],
    }


def _validate_target_ids(
    target_ids: Sequence[str], record_ids: set[str], label: str
) -> None:
    unknown = sorted(set(target_ids) - record_ids)
    if unknown:
        raise ValueError(f"{label} references unknown records: {unknown}")


def _all_evidence(state: InterviewState) -> Iterable[EvidenceRef]:
    for claim in state.claims:
        yield from claim.evidence
    for issue in state.issues:
        yield from issue.evidence
    for contradiction in state.contradictions:
        yield from contradiction.evidence
    yield from state.completion.confirmation_evidence


def _validate_business_model(model: BusinessModel) -> None:
    _unique_ids(model.actors, "actor")
    _unique_ids(model.process_steps, "process step")
    _unique_ids(model.flows, "flow")
    _unique_ids(model.systems, "system")
    _unique_ids(model.data_types, "data type")
    _unique_ids(model.data_operations, "data operation")
    actor_ids = {item.id for item in model.actors}
    step_ids = {item.id for item in model.process_steps}
    system_ids = {item.id for item in model.systems}
    data_ids = {item.id for item in model.data_types}
    operation_ids = {item.id for item in model.data_operations}
    if operation_ids & step_ids:
        raise ValueError("data operation IDs must not overlap process step IDs")

    for step in model.process_steps:
        _validate_link(step.actor, actor_ids, f"process step {step.id!r} actor")
        _validate_list(step.inputs, data_ids, f"process step {step.id!r} inputs")
        _validate_list(step.outputs, data_ids, f"process step {step.id!r} outputs")

    for flow in model.flows:
        if flow.from_id not in step_ids and flow.from_id != SOURCE_ENDPOINT:
            raise ValueError(f"flow {flow.id!r} has unknown from endpoint")
        if flow.to_id not in step_ids and flow.to_id != SINK_ENDPOINT:
            raise ValueError(f"flow {flow.id!r} has unknown to endpoint")
        if flow.kind == "source_boundary" and flow.from_id != SOURCE_ENDPOINT:
            raise ValueError("source_boundary flow must start at SOURCE")
        if flow.kind == "sink_boundary" and flow.to_id != SINK_ENDPOINT:
            raise ValueError("sink_boundary flow must end at SINK")
        if flow.kind in {"normal", "branch", "exception"} and (
            flow.from_id in {SOURCE_ENDPOINT, SINK_ENDPOINT}
            or flow.to_id in {SOURCE_ENDPOINT, SINK_ENDPOINT}
        ):
            raise ValueError("SOURCE/SINK must not be used by a normal business flow")

    for operation in model.data_operations:
        if operation.process_step_id not in step_ids:
            raise ValueError(
                f"data operation {operation.id!r} has unknown process step"
            )
        _validate_link(
            operation.system, system_ids, f"data operation {operation.id!r} system"
        )
        _validate_link(
            operation.data_type,
            data_ids,
            f"data operation {operation.id!r} data type",
        )


_CLAIM_PREDICATES = {
    "process_step": {"activity", "actor", "inputs", "outputs"},
    "flow": {"relation", "condition"},
    "resource_usage": {"crud", "system", "data_type"},
}


def _validate_active_claims(model: BusinessModel, claims: Sequence[Claim]) -> None:
    """Ensure active claims are a unique, lossless projection explanation."""
    steps = {item.id: item for item in model.process_steps}
    flows = {item.id: item for item in model.flows}
    operations = {item.id: item for item in model.data_operations}
    active_keys: set[tuple[str, str, str]] = set()

    for claim in claims:
        predicates = _CLAIM_PREDICATES[claim.record_type]
        if claim.predicate not in predicates:
            raise ValueError(
                f"claim {claim.id!r} has unsupported predicate "
                f"{claim.predicate!r} for {claim.record_type}"
            )
        target = (
            steps.get(claim.target_id)
            if claim.record_type == "process_step"
            else flows.get(claim.target_id)
            if claim.record_type == "flow"
            else operations.get(claim.target_id)
        )
        if target is None:
            raise ValueError(
                f"claim {claim.id!r} targets unknown {claim.record_type} "
                f"record {claim.target_id!r}"
            )
        if claim.status == "rejected":
            continue

        key = (claim.record_type, claim.target_id, claim.predicate)
        if key in active_keys:
            raise ValueError(
                f"multiple active claims target {claim.record_type}/"
                f"{claim.target_id}/{claim.predicate}"
            )
        active_keys.add(key)
        _validate_active_claim_value(claim, target)

    required_keys: list[tuple[str, str, str]] = []
    for step in steps.values():
        if step.activity.state != "unset":
            required_keys.append(("process_step", step.id, "activity"))
        if step.actor.state != "unset":
            required_keys.append(("process_step", step.id, "actor"))
        if step.inputs.state != "unset":
            required_keys.append(("process_step", step.id, "inputs"))
        if step.outputs.state != "unset":
            required_keys.append(("process_step", step.id, "outputs"))
    for flow in flows.values():
        required_keys.append(("flow", flow.id, "relation"))
        if flow.condition.state != "unset":
            required_keys.append(("flow", flow.id, "condition"))
    for operation in operations.values():
        required_keys.extend(
            (
                ("resource_usage", operation.id, "crud"),
                ("resource_usage", operation.id, "system"),
                ("resource_usage", operation.id, "data_type"),
            )
        )
    missing = [key for key in required_keys if key not in active_keys]
    if missing:
        raise ValueError(f"projection has no active claim for fields: {missing}")


def _validate_active_claim_value(claim: Claim, target: BaseModel) -> None:
    if claim.record_type == "process_step":
        step = target
        if not isinstance(step, ProcessStep):
            raise TypeError("process-step claim target has an invalid type")
        if claim.predicate == "activity":
            expected = step.activity
        elif claim.predicate == "actor":
            expected = _link_as_information_value(step.actor)
        else:
            expected_list = step.inputs if claim.predicate == "inputs" else step.outputs
            _validate_claim_list_value(claim, expected_list)
            return
        if claim.value != expected:
            raise ValueError(
                f"active claim {claim.id!r} does not match the current projection"
            )
        return

    if claim.record_type == "flow":
        flow = target
        if not isinstance(flow, ProcessFlow):
            raise TypeError("flow claim target has an invalid type")
        expected = (
            InformationValue(state="value", value=f"{flow.from_id}->{flow.to_id}")
            if claim.predicate == "relation"
            else flow.condition
        )
        if claim.value != expected:
            raise ValueError(
                f"active claim {claim.id!r} does not match the current projection"
            )
        return

    operation = target
    if not isinstance(operation, DataOperation):
        raise TypeError("resource-usage claim target has an invalid type")
    if claim.predicate == "crud":
        expected = InformationValue(state="value", value=operation.crud)
    elif claim.predicate == "system":
        expected = _link_as_information_value(operation.system)
    else:
        expected = _link_as_information_value(operation.data_type)
    if claim.value != expected:
        raise ValueError(
            f"active claim {claim.id!r} does not match the current projection"
        )


def _link_as_information_value(link: EntityLink) -> InformationValue:
    return InformationValue(
        state=link.state,
        value=link.entity_id if link.state == "value" else None,
    )


def _validate_claim_list_value(claim: Claim, expected: EntityList) -> None:
    if claim.value.state != expected.state:
        raise ValueError(
            f"active claim {claim.id!r} does not match the current projection"
        )
    if expected.state != "value":
        return
    try:
        raw = json.loads(claim.value.value or "")
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"active claim {claim.id!r} has an invalid data-list value"
        ) from exc
    if (
        not isinstance(raw, list)
        or not all(isinstance(item, str) and item for item in raw)
        or tuple(raw) != expected.entity_ids
    ):
        raise ValueError(
            f"active claim {claim.id!r} does not match the current projection"
        )


def _validate_link(link: EntityLink, known_ids: set[str], label: str) -> None:
    if link.state == "value" and link.entity_id not in known_ids:
        raise ValueError(f"{label} references unknown entity {link.entity_id!r}")


def _validate_list(value: EntityList, known_ids: set[str], label: str) -> None:
    if value.state == "value":
        unknown = sorted(set(value.entity_ids) - known_ids)
        if unknown:
            raise ValueError(f"{label} references unknown data types: {unknown}")


__all__ = [
    "ActorRecord",
    "BusinessModel",
    "Claim",
    "ClaimStatus",
    "Completion",
    "ContentCompleteness",
    "Contradiction",
    "CrudOperation",
    "DataOperation",
    "DataTypeRecord",
    "EntityLink",
    "EntityList",
    "EvidenceCitation",
    "EvidenceRef",
    "FlowKind",
    "InformationState",
    "InformationValue",
    "InterviewHarness",
    "InterviewState",
    "InterviewStateError",
    "Issue",
    "IssueKind",
    "OpenQuestion",
    "ProcessFlow",
    "ProcessStep",
    "SOURCE_ENDPOINT",
    "SINK_ENDPOINT",
    "SemanticSupport",
    "SystemRecord",
    "Utterance",
]
