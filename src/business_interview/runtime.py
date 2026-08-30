"""Core contracts for a live, multi-turn Business Interview.

This module is deliberately independent of Inspect AI.  It owns the durable
JSON state for one interview, the public-message/observation provenance
boundary, and ingestion of an already validated stakeholder response.  The
Inspect adapter may persist this state, but it must not implement a second
runtime or graph mutation language.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, Literal

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
)

from business_interview.models import (
    AbsentType,
    AgentGraph,
    ConceptRef,
    DontKnowType,
    EvidenceRef,
    InterviewEvaluationContext,
    LedgerMessage,
    ObservationRecord,
)
from business_interview.stakeholders.knowledge import (
    StakeholderKnowledge,
    validate_stakeholder_knowledge,
)
from business_interview.stakeholders.response import (
    ConceptAlignmentAssertion,
    SemanticAnnotation,
    SemanticResponsePlan,
    StakeholderResponse,
    TerminologyConfirmation,
    validate_stakeholder_response,
)


class InterviewRuntimeError(ValueError):
    """Raised when a live interview protocol operation is not allowed."""


RuntimeStateError = InterviewRuntimeError


class PublicMessageRecord(BaseModel):
    """One message in the raw public conversation ledger.

    Only the message text and ordinary conversation role are retained here.
    Private annotations and alignments belong exclusively to
    :class:`SemanticLedger`.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    turn: int = Field(
        ge=0,
        validation_alias=AliasChoices("turn", "public_message_turn", "message_turn"),
    )
    role: str = Field(min_length=1)
    content: str = Field(min_length=1, validation_alias=AliasChoices("content", "text"))

    @property
    def public_message_turn(self) -> int:
        return self.turn

    @property
    def text(self) -> str:
        return self.content


class InterviewProtocolState(BaseModel):
    """Explicit completion/incomplete state for a live interview."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["active", "completed", "incomplete"] = "active"
    completion_reason: str | None = None
    failure_reason: str | None = None
    terminal_turn: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _validate_terminal_fields(self) -> InterviewProtocolState:
        if self.status == "completed":
            if not self.completion_reason:
                raise ValueError("completed protocol requires completion_reason")
            if self.failure_reason is not None:
                raise ValueError("completed protocol cannot have failure_reason")
        elif self.status == "incomplete":
            if not self.failure_reason:
                raise ValueError("incomplete protocol requires failure_reason")
            if self.completion_reason is not None:
                raise ValueError("incomplete protocol cannot have completion_reason")
        elif self.completion_reason is not None or self.failure_reason is not None:
            raise ValueError("active protocol cannot have a terminal reason")
        return self

    @property
    def completed(self) -> bool:
        return self.status == "completed"

    @property
    def incomplete(self) -> bool:
        return self.status == "incomplete"

    @property
    def active(self) -> bool:
        return self.status == "active"

    @property
    def protocol_completed(self) -> bool:
        """Evaluator-compatible completion flag."""
        return self.completed


class SemanticLedgerEntry(BaseModel):
    """Private sidecar facts associated with exactly one public observation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    public_message_turn: int = Field(
        ge=0,
        validation_alias=AliasChoices("public_message_turn", "turn", "message_turn"),
    )
    observation_id: str = Field(min_length=1)
    annotations: tuple[SemanticAnnotation, ...] = Field(default_factory=tuple)
    alignments: tuple[ConceptAlignmentAssertion, ...] = Field(default_factory=tuple)
    terminology: tuple[TerminologyConfirmation, ...] = Field(default_factory=tuple)

    @property
    def turn(self) -> int:
        """Short alias for the originating public-message turn."""
        return self.public_message_turn

    @property
    def message_turn(self) -> int:
        return self.public_message_turn


class SemanticLedger(BaseModel):
    """Private, append-only semantic sidecar ledger.

    The model stores no inferred facts and no prose-derived reconstruction.  A
    caller must first run ``validate_stakeholder_response`` and then append
    the exact response sidecar through ``ingest_stakeholder_response``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    entries: tuple[SemanticLedgerEntry, ...] = Field(
        default_factory=tuple,
        validation_alias=AliasChoices("entries", "records"),
    )

    @model_validator(mode="after")
    def _entries_are_unique(self) -> SemanticLedger:
        observations = [entry.observation_id for entry in self.entries]
        turns = [entry.public_message_turn for entry in self.entries]
        if len(observations) != len(set(observations)):
            raise ValueError("SemanticLedger observation IDs must be unique")
        if len(turns) != len(set(turns)):
            raise ValueError("SemanticLedger public-message turns must be unique")
        return self

    def for_observation(self, observation_id: str) -> SemanticLedgerEntry | None:
        """Return the private entry for one observation ID, if present."""
        return next(
            (entry for entry in self.entries if entry.observation_id == observation_id),
            None,
        )

    @property
    def records(self) -> tuple[SemanticLedgerEntry, ...]:
        return self.entries

    @property
    def annotations(self) -> tuple[SemanticAnnotation, ...]:
        """Flattened annotation view for ledger inspection, kept private."""
        return tuple(item for entry in self.entries for item in entry.annotations)

    @property
    def alignments(self) -> tuple[ConceptAlignmentAssertion, ...]:
        return tuple(item for entry in self.entries for item in entry.alignments)

    @property
    def terminology(self) -> tuple[TerminologyConfirmation, ...]:
        return tuple(item for entry in self.entries for item in entry.terminology)

    def append_response(
        self,
        knowledge: StakeholderKnowledge,
        plan: SemanticResponsePlan,
        response: StakeholderResponse,
        *,
        public_message_turn: int,
        observation_id: str,
    ) -> SemanticLedger:
        """Validate then append one response sidecar atomically."""
        validate_stakeholder_knowledge(knowledge)
        validated = validate_stakeholder_response(knowledge, plan, response)
        return self.append_validated(
            validated,
            public_message_turn=public_message_turn,
            observation_id=observation_id,
        )

    def append_validated(
        self,
        response: StakeholderResponse,
        *,
        public_message_turn: int,
        observation_id: str,
    ) -> SemanticLedger:
        """Append a sidecar that the caller has already validated.

        This low-level method is intentionally named ``append_validated``.
        Normal callers should use ``ingest_stakeholder_response`` so that the
        knowledge/plan validator is always run before the append.
        """
        if self.entries and public_message_turn <= self.entries[-1].public_message_turn:
            raise ValueError(
                "SemanticLedger entries must be appended in public-message order"
            )
        entry = SemanticLedgerEntry(
            public_message_turn=public_message_turn,
            observation_id=observation_id,
            annotations=response.annotations,
            alignments=response.alignments,
            terminology=response.terminology,
        )
        return SemanticLedger(entries=(*self.entries, entry))


def _span_exists(text: str, quote: str, occurrence: int) -> bool:
    if occurrence < 0 or not quote:
        return False
    start = -1
    for _ in range(occurrence + 1):
        start = text.find(quote, start + 1)
        if start < 0:
            return False
    return True


def _validate_sidecar_spans(
    observation: ObservationRecord,
    entry: SemanticLedgerEntry,
    *,
    initial: bool,
) -> None:
    if initial and (entry.annotations or entry.alignments or entry.terminology):
        raise ValueError("initial observations cannot contain semantic sidecar events")
    events = (*entry.annotations, *entry.alignments, *entry.terminology)
    for event in events:
        if not _span_exists(observation.text, event.quote, event.occurrence):
            raise ValueError(
                f"semantic sidecar quote is not an exact observation span: "
                f"{observation.id!r}"
            )


def _agent_graph_errors(graph: AgentGraph) -> list[str]:
    errors = list(graph.structure_errors())
    errors.extend(
        f"node mapping key does not match node.id: {key!r}"
        for key, node in graph.nodes.items()
        if key != node.id
    )
    errors.extend(
        f"edge mapping key does not match edge.id: {key!r}"
        for key, edge in graph.edges.items()
        if key != edge.id
    )
    if len(graph.start_node_ids) != len(set(graph.start_node_ids)):
        errors.append("start_node_ids must be unique")
    if len(graph.end_node_ids) != len(set(graph.end_node_ids)):
        errors.append("end_node_ids must be unique")
    return errors


def _validate_graph_evidence(
    graph: AgentGraph,
    observations: Sequence[ObservationRecord],
) -> None:
    """Validate every graph EvidenceRef against the live observation ledger."""
    observation_text = {
        observation.id: observation.text for observation in observations
    }

    def check(item: Any, subject: str) -> None:
        if not isinstance(item, EvidenceRef):
            return
        text = observation_text.get(item.observation_id)
        if text is None:
            raise ValueError(
                f"{subject} references unknown observation {item.observation_id!r}"
            )
        if item.quote and item.resolve_span(text) is None:
            raise ValueError(
                f"{subject} quote is not an exact span of observation "
                f"{item.observation_id!r}"
            )

    for node in graph.nodes.values():
        for property_name in (
            "activity",
            "actor",
            "system",
            "reads",
            "writes",
            "rationale",
        ):
            value = node.slot_value(property_name)
            if isinstance(value, (AbsentType, DontKnowType)):
                for item in value.evidence:
                    check(item, f"node {node.id}:{property_name}")
            for ref in node.refs(property_name):
                for item in ref.evidence:
                    check(item, f"node {node.id}:{property_name}")
    for edge in graph.edges.values():
        for item in edge.evidence:
            check(item, f"edge {edge.id}")
        condition = edge.condition
        if isinstance(condition, (AbsentType, DontKnowType)):
            for item in condition.evidence:
                check(item, f"edge {edge.id}:condition")
        if isinstance(condition, ConceptRef):
            for item in condition.evidence:
                check(item, f"edge {edge.id}:condition")
    for concept in graph.concepts.values():
        for item in concept.mentions:
            check(item, f"concept {concept.id}")


class LiveInterviewStore(BaseModel):
    """JSON-serializable durable state for one live interview.

    ``agent_graph`` and the public ledger are candidate-visible state.  The
    ``semantic_ledger`` is private runtime state and is never converted into
    an Agent chat message.  Stakeholder knowledge itself is supplied to the
    stakeholder adapter separately and is intentionally not part of this
    candidate-facing state contract.
    """

    model_config = ConfigDict(extra="forbid")

    scenario_id: str = Field(min_length=1)
    agent_graph: AgentGraph = Field(
        default_factory=AgentGraph,
        validation_alias=AliasChoices("agent_graph", "agent"),
    )
    observations: tuple[ObservationRecord, ...] = Field(default_factory=tuple)
    public_message_ledger: tuple[PublicMessageRecord, ...] = Field(
        default_factory=tuple,
        validation_alias=AliasChoices(
            "public_message_ledger",
            "raw_public_message_ledger",
            "raw_public_messages",
            "raw_messages",
            "public_messages",
            "messages",
            "public_ledger",
        ),
    )
    semantic_ledger: SemanticLedger = Field(default_factory=SemanticLedger)
    protocol_state: InterviewProtocolState = Field(
        default_factory=InterviewProtocolState,
        validation_alias=AliasChoices("protocol_state", "protocol", "completion_state"),
    )
    max_turns: int = Field(default=8, ge=1)
    candidate_turns: int = Field(default=0, ge=0)
    stakeholder_turns: int = Field(default=0, ge=0)
    question_count: int = Field(default=0, ge=0)
    initial_observation_count: int = Field(default=0, ge=0)

    @model_validator(mode="before")
    @classmethod
    def _normalize_runtime_aliases(cls, value: object) -> object:
        if not isinstance(value, Mapping):
            return value
        payload = dict(value)
        if "public_message_ledger" not in payload:
            for alias in (
                "raw_public_message_ledger",
                "raw_public_messages",
                "raw_messages",
                "public_messages",
                "messages",
                "public_ledger",
            ):
                if alias in payload:
                    payload["public_message_ledger"] = payload[alias]
                    break
        if "agent_graph" not in payload and "graph" in payload:
            payload["agent_graph"] = payload["graph"]
        if "protocol_state" not in payload:
            if payload.get("protocol_completed"):
                payload["protocol_state"] = {
                    "status": "completed",
                    "completion_reason": "agent_declared",
                }
            elif payload.get("termination_reason"):
                payload["protocol_state"] = {
                    "status": "incomplete",
                    "failure_reason": payload["termination_reason"],
                }
        if "candidate_turns" not in payload and "turn_count" in payload:
            payload["candidate_turns"] = payload["turn_count"]
        if "max_turns" not in payload and "max_turn_count" in payload:
            payload["max_turns"] = payload["max_turn_count"]
        for alias in (
            "raw_public_message_ledger",
            "raw_public_messages",
            "raw_messages",
            "public_messages",
            "messages",
            "public_ledger",
            "graph",
            "protocol_completed",
            "termination_reason",
            "turn_count",
            "max_turn_count",
        ):
            payload.pop(alias, None)
        return payload

    @model_validator(mode="after")
    def _validate_ledger_consistency(self) -> LiveInterviewStore:
        observations = [observation.id for observation in self.observations]
        if len(observations) != len(set(observations)):
            raise ValueError("observation IDs must be unique")
        observation_turns = [observation.turn for observation in self.observations]
        if observation_turns != sorted(observation_turns):
            raise ValueError("observations must be ordered by public-message turn")
        if len(observation_turns) != len(set(observation_turns)):
            raise ValueError("observation turns must be unique")
        public_turns = [message.turn for message in self.public_message_ledger]
        if len(public_turns) != len(set(public_turns)):
            raise ValueError("public message turns must be unique")
        if public_turns != list(range(len(public_turns))):
            raise ValueError("public message turns must be contiguous and ordered")
        if any(
            message.role not in ("assistant", "user")
            for message in self.public_message_ledger
        ):
            raise ValueError("public message roles must be assistant or user")
        if self.initial_observation_count + self.stakeholder_turns != len(
            self.observations
        ):
            raise ValueError(
                "observation count must equal initial_observation_count plus "
                "stakeholder_turns"
            )
        entries_by_observation = {
            entry.observation_id: entry for entry in self.semantic_ledger.entries
        }
        entry_ids = tuple(
            entry.observation_id for entry in self.semantic_ledger.entries
        )
        if entry_ids != tuple(observations):
            raise ValueError("SemanticLedger entries must match observations in order")
        observations_by_id = {
            observation.id: observation for observation in self.observations
        }
        public_by_turn = {
            message.turn: message for message in self.public_message_ledger
        }
        for index, observation in enumerate(self.observations):
            message = public_by_turn.get(observation.turn)
            if (
                message is None
                or message.role != "user"
                or message.content != observation.text
            ):
                raise ValueError(
                    "each observation must match an exact public user message"
                )
            entry = entries_by_observation[observation.id]
            if (
                entry.public_message_turn != observation.turn
                or entry.observation_id not in observations_by_id
            ):
                raise ValueError(
                    "each SemanticLedger entry must match its observation turn"
                )
            _validate_sidecar_spans(
                observation,
                entry,
                initial=index < self.initial_observation_count,
            )
        graph_errors = _agent_graph_errors(self.agent_graph)
        if graph_errors:
            raise ValueError("AgentGraph is invalid:\n- " + "\n- ".join(graph_errors))
        _validate_graph_evidence(self.agent_graph, self.observations)
        if self.candidate_turns > self.max_turns:
            raise ValueError("candidate_turns cannot exceed max_turns")
        if self.question_count < self.stakeholder_turns:
            raise ValueError("question_count cannot be below stakeholder_turns")
        if self.question_count > self.candidate_turns:
            raise ValueError("question_count cannot exceed candidate_turns")
        if self.question_count > self.max_turns:
            raise ValueError("question_count cannot exceed max_turns")
        if self.question_count > self.stakeholder_turns + 1:
            raise ValueError(
                "question_count may exceed stakeholder_turns by at most one pending question"
            )
        pending_question = bool(
            self.public_message_ledger
            and self.public_message_ledger[-1].role == "assistant"
        )
        if pending_question != (self.question_count == self.stakeholder_turns + 1):
            raise ValueError("public question and stakeholder counter are inconsistent")
        if self.protocol_state.active:
            if self.protocol_state.terminal_turn is not None:
                raise ValueError("active protocol cannot have terminal_turn")
        else:
            if self.protocol_state.terminal_turn != self.candidate_turns:
                raise ValueError("terminal_turn must equal candidate_turns")
            if pending_question:
                raise ValueError("terminal protocol cannot have a pending question")
        return self

    @property
    def agent(self) -> AgentGraph:
        """Store-shaped alias used by replay/scoring callers."""
        return self.agent_graph

    @property
    def graph(self) -> AgentGraph:
        return self.agent_graph

    @property
    def raw_public_messages(self) -> tuple[PublicMessageRecord, ...]:
        return self.public_message_ledger

    @property
    def raw_messages(self) -> tuple[PublicMessageRecord, ...]:
        return self.public_message_ledger

    @property
    def message_ledger(self) -> tuple[PublicMessageRecord, ...]:
        return self.public_message_ledger

    @property
    def public_messages(self) -> tuple[PublicMessageRecord, ...]:
        return self.public_message_ledger

    @property
    def protocol(self) -> InterviewProtocolState:
        return self.protocol_state

    @property
    def completed(self) -> bool:
        return self.protocol_state.completed

    @property
    def incomplete(self) -> bool:
        return self.protocol_state.incomplete

    @property
    def active(self) -> bool:
        return self.protocol_state.active

    @property
    def protocol_completed(self) -> bool:
        return self.protocol_state.completed

    @property
    def termination_reason(self) -> str | None:
        return (
            self.protocol_state.completion_reason or self.protocol_state.failure_reason
        )

    @property
    def turn_count(self) -> int:
        """Candidate model-turn count used by the hard limit."""
        return self.candidate_turns

    @property
    def messages_by_turn(self) -> dict[int, LedgerMessage]:
        """Build the sparse evaluator provenance ledger from observations."""
        return {
            observation.turn: LedgerMessage(role="user", content=observation.text)
            for observation in self.observations
        }

    def evaluation_context(self) -> InterviewEvaluationContext:
        """Construct the existing evaluator context without reparsing prose."""
        return InterviewEvaluationContext(
            observations=self.observations,
            messages_by_turn=self.messages_by_turn,
            protocol_completed=self.protocol_state.completed,
        )

    def _copy(self, **updates: Any) -> LiveInterviewStore:
        payload = self.model_dump(mode="python")
        payload.update(updates)
        try:
            return LiveInterviewStore.model_validate(payload)
        except (TypeError, ValidationError) as exc:
            raise InterviewRuntimeError(
                "could not update live interview state"
            ) from exc

    def _require_active(self) -> None:
        if not self.protocol_state.active:
            raise InterviewRuntimeError(
                f"interview is terminal ({self.protocol_state.status}); "
                "no further runtime mutation is allowed"
            )

    def record_candidate_turn(self) -> LiveInterviewStore:
        """Record one candidate model invocation under the hard turn limit."""
        self._require_active()
        if self.candidate_turns >= self.max_turns:
            raise InterviewRuntimeError("maximum interview turn count exhausted")
        return self._copy(candidate_turns=self.candidate_turns + 1)

    def record_candidate_question(self, text: str) -> LiveInterviewStore:
        """Append one candidate question to the public message ledger."""
        self._require_active()
        if not isinstance(text, str) or not text.strip():
            raise InterviewRuntimeError("candidate question must not be blank")
        if self.public_message_ledger and self.public_message_ledger[-1].role != "user":
            # A second question without a stakeholder response would make the
            # observation-to-message provenance ambiguous.
            raise InterviewRuntimeError("a stakeholder response is pending")
        turn = self._next_public_turn()
        message = PublicMessageRecord(turn=turn, role="assistant", content=text)
        return self._copy(
            public_message_ledger=(*self.public_message_ledger, message),
            question_count=self.question_count + 1,
        )

    def apply_agent_graph(self, graph: AgentGraph) -> LiveInterviewStore:
        """Replace the graph after a pure core mutation operation."""
        self._require_active()
        errors = _agent_graph_errors(graph)
        if errors:
            raise InterviewRuntimeError(
                "cannot store invalid AgentGraph:\n- " + "\n- ".join(errors)
            )
        try:
            _validate_graph_evidence(graph, self.observations)
        except ValueError as exc:
            raise InterviewRuntimeError(str(exc)) from exc
        return self._copy(agent_graph=graph)

    def ingest_stakeholder_response(
        self,
        knowledge: StakeholderKnowledge,
        plan: SemanticResponsePlan,
        response: StakeholderResponse,
        *,
        observation_id: str | None = None,
    ) -> LiveInterviewStore:
        """Validate and ingest one response, preserving its exact sidecar.

        Validation happens before any new state is built.  The response's
        ``message`` is the only text added to the public ledger and the Agent
        conversation; annotations, alignments, and terminology are copied
        only into the private semantic ledger.
        """
        self._require_active()
        if not self.public_message_ledger:
            raise InterviewRuntimeError("cannot ingest a response before a question")
        if self.public_message_ledger[-1].role != "assistant":
            raise InterviewRuntimeError("no candidate question is awaiting a response")
        validate_stakeholder_knowledge(knowledge)
        validated = validate_stakeholder_response(knowledge, plan, response)
        public_turn = self._next_public_turn()
        resolved_observation_id = observation_id or f"obs_{public_turn}"
        if any(
            observation.id == resolved_observation_id
            for observation in self.observations
        ):
            raise InterviewRuntimeError(
                f"observation ID already exists: {resolved_observation_id!r}"
            )
        observation = ObservationRecord(
            id=resolved_observation_id,
            text=validated.message,
            turn=public_turn,
        )
        message = PublicMessageRecord(
            turn=public_turn,
            role="user",
            content=validated.message,
        )
        ledger = self.semantic_ledger.append_validated(
            validated,
            public_message_turn=public_turn,
            observation_id=resolved_observation_id,
        )
        return self._copy(
            observations=(*self.observations, observation),
            public_message_ledger=(*self.public_message_ledger, message),
            semantic_ledger=ledger,
            stakeholder_turns=self.stakeholder_turns + 1,
        )

    def mark_complete(
        self,
        reason: str = "agent_declared",
    ) -> LiveInterviewStore:
        """Mark the interview complete through an explicit Agent declaration."""
        self._require_active()
        reason = reason.strip() if isinstance(reason, str) else ""
        if not reason:
            raise InterviewRuntimeError("completion reason must not be blank")
        if (
            self.public_message_ledger
            and self.public_message_ledger[-1].role == "assistant"
        ):
            raise InterviewRuntimeError(
                "cannot complete while a stakeholder response is pending"
            )
        protocol = InterviewProtocolState(
            status="completed",
            completion_reason=reason,
            terminal_turn=self.candidate_turns,
        )
        return self._copy(protocol_state=protocol)

    def mark_incomplete(
        self,
        reason: str = "max_turns_exhausted",
    ) -> LiveInterviewStore:
        """Record an explicit runtime failure without claiming completion."""
        self._require_active()
        reason = reason.strip() if isinstance(reason, str) else ""
        if not reason:
            raise InterviewRuntimeError("incomplete reason must not be blank")
        protocol = InterviewProtocolState(
            status="incomplete",
            failure_reason=reason,
            terminal_turn=self.candidate_turns,
        )
        return self._copy(protocol_state=protocol)

    def _next_public_turn(self) -> int:
        if not self.public_message_ledger:
            return 0
        return self.public_message_ledger[-1].turn + 1


def create_live_interview_store(
    scenario_id: str,
    *,
    initial_graph: AgentGraph | None = None,
    initial_public_messages: Sequence[
        PublicMessageRecord | LedgerMessage | Mapping[str, Any] | tuple[str, str]
    ] = (),
    max_turns: int = 8,
    max_turn_count: int | None = None,
) -> LiveInterviewStore:
    """Create deterministic live state from public initial history only."""
    if not isinstance(scenario_id, str) or not scenario_id.strip():
        raise InterviewRuntimeError("scenario_id must not be blank")
    if max_turn_count is not None:
        max_turns = max_turn_count
    if max_turns < 1:
        raise InterviewRuntimeError("max_turns must be positive")
    messages: list[PublicMessageRecord] = []
    for index, raw in enumerate(initial_public_messages):
        if isinstance(raw, PublicMessageRecord):
            message = raw
        elif isinstance(raw, LedgerMessage):
            if raw.content is None:
                raise InterviewRuntimeError(
                    "initial public message content is required"
                )
            message = PublicMessageRecord(
                turn=index,
                role=raw.role,
                content=raw.content,
            )
        elif isinstance(raw, tuple):
            if len(raw) != 2:
                raise InterviewRuntimeError("initial message tuples need role/content")
            message = PublicMessageRecord(turn=index, role=raw[0], content=raw[1])
        else:
            payload = dict(raw)
            payload.setdefault("turn", index)
            try:
                message = PublicMessageRecord.model_validate(payload)
            except (TypeError, ValidationError) as exc:
                raise InterviewRuntimeError("invalid initial public message") from exc
        if message.turn != index:
            # Initial history is normalized to one stable, contiguous public
            # turn sequence; generated messages continue after it.
            message = PublicMessageRecord(
                turn=index,
                role=message.role,
                content=message.content,
            )
        messages.append(message)
    graph = initial_graph or AgentGraph()
    errors = _agent_graph_errors(graph)
    if errors:
        raise InterviewRuntimeError(
            "initial AgentGraph is invalid:\n- " + "\n- ".join(errors)
        )
    initial_observations = tuple(
        ObservationRecord(
            id=f"obs_{message.turn}",
            text=message.content,
            turn=message.turn,
        )
        for message in messages
        if message.role == "user"
    )
    initial_entries = tuple(
        SemanticLedgerEntry(
            public_message_turn=observation.turn,
            observation_id=observation.id,
        )
        for observation in initial_observations
    )
    return LiveInterviewStore(
        scenario_id=scenario_id,
        agent_graph=graph,
        observations=initial_observations,
        public_message_ledger=tuple(messages),
        semantic_ledger=SemanticLedger(entries=initial_entries),
        max_turns=max_turns,
        initial_observation_count=len(initial_observations),
    )


def record_candidate_turn(store: LiveInterviewStore) -> LiveInterviewStore:
    """Functional facade for one candidate model turn."""
    return store.record_candidate_turn()


def record_candidate_question(
    store: LiveInterviewStore,
    text: str,
) -> LiveInterviewStore:
    """Functional facade for appending one candidate question."""
    return store.record_candidate_question(text)


def ingest_stakeholder_response(
    store: LiveInterviewStore,
    knowledge: StakeholderKnowledge,
    plan: SemanticResponsePlan,
    response: StakeholderResponse,
    *,
    observation_id: str | None = None,
) -> LiveInterviewStore:
    """Functional facade for validated response ingestion."""
    return store.ingest_stakeholder_response(
        knowledge,
        plan,
        response,
        observation_id=observation_id,
    )


ingest_response = ingest_stakeholder_response


def apply_agent_graph_mutation(
    store: LiveInterviewStore,
    operation: Callable[[AgentGraph], AgentGraph],
) -> LiveInterviewStore:
    """Apply one pure graph operation to active live state."""
    store._require_active()
    try:
        graph = operation(store.agent_graph)
    except InterviewRuntimeError:
        raise
    except Exception as exc:
        raise InterviewRuntimeError("AgentGraph mutation failed") from exc
    return store.apply_agent_graph(graph)


def mark_interview_complete(
    store: LiveInterviewStore,
    reason: str = "agent_declared",
) -> LiveInterviewStore:
    """Functional completion facade."""
    return store.mark_complete(reason)


def mark_max_turn_exhausted(
    store: LiveInterviewStore,
    reason: str = "max_turns_exhausted",
) -> LiveInterviewStore:
    """Functional incomplete-protocol facade."""
    return store.mark_incomplete(reason)


def build_evaluation_context(store: LiveInterviewStore) -> InterviewEvaluationContext:
    """Return the existing evaluator input for a live session."""
    return store.evaluation_context()


# Short aliases match the names used in design notes and make the contracts
# discoverable without duplicating models.
Observation = ObservationRecord
PublicMessage = PublicMessageRecord
ProtocolState = InterviewProtocolState
SemanticLedgerRecord = SemanticLedgerEntry
LiveInterviewRuntime = LiveInterviewStore
InterviewSession = LiveInterviewStore
InterviewSessionState = LiveInterviewStore


__all__ = [
    "InterviewProtocolState",
    "InterviewRuntimeError",
    "InterviewSession",
    "InterviewSessionState",
    "LiveInterviewRuntime",
    "LiveInterviewStore",
    "Observation",
    "ProtocolState",
    "PublicMessage",
    "PublicMessageRecord",
    "RuntimeStateError",
    "SemanticLedger",
    "SemanticLedgerEntry",
    "SemanticLedgerRecord",
    "apply_agent_graph_mutation",
    "build_evaluation_context",
    "create_live_interview_store",
    "ingest_response",
    "ingest_stakeholder_response",
    "mark_interview_complete",
    "mark_max_turn_exhausted",
    "record_candidate_question",
    "record_candidate_turn",
]
