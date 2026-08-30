"""Inspect solver for the Phase 13 multi-turn interview vertical slice."""

# The workspace-level auxiliary resolver may not see the Inspect dev group.
# Project-level ``uv run pyright`` is authoritative for this adapter.
# pyright: reportMissingImports=false

from __future__ import annotations

from collections.abc import Sequence
from typing import cast

from inspect_ai import Task, task
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageUser,
)
from inspect_ai.solver import Generate, Solver, TaskState, solver

from business_interview.evaluation import KnowledgeCoverageView
from business_interview.models import (
    AgentGraph,
    BusinessProcessGraph,
    validate_canonical_graph,
)
from business_interview.runtime import (
    InterviewRuntimeError,
    LiveInterviewStore,
    create_live_interview_store,
    mark_max_turn_exhausted,
)
from business_interview.scenarios import get_scenario
from business_interview.stakeholders import (
    EdgeProperty,
    NodeProperty,
    StakeholderKnowledge,
    StakeholderProfile,
    knowledge_coverage_view,
    project_knowledge,
    validate_stakeholder_knowledge,
)

from .live_scorer import phase13_primary_scorer
from .live_store import (
    BusinessInterviewLiveStore,
    persist_evaluation_inputs,
    persist_live_state,
)
from .stakeholder import (
    StakeholderResponseError,
    invoke_stakeholder_response_with_plan,
)
from .tools import build_interview_tools

_CANDIDATE_SYSTEM_MARKER = "business-interview-bench phase13 candidate"
_CANDIDATE_SYSTEM = f"""{_CANDIDATE_SYSTEM_MARKER}

You are the candidate interviewer in a multi-turn Business Interview.
Use only the public conversation and the current AgentGraph returned by the
available graph tools. Ask one clear public question at a time. Build and
revise your AgentGraph with the tools when the stakeholder provides evidence;
attach evidence only to exact public observation text. Runtime-owned hidden
state is unavailable to you. Do not put internal graph IDs in your public
questions. When the interview is complete, call complete_interview explicitly
instead of merely saying that you are done.
"""


class MultiTurnInterviewError(RuntimeError):
    """Raised for adapter setup or candidate-turn failures."""


def _public_pairs(messages: Sequence[ChatMessage]) -> list[tuple[str, str]]:
    """Extract only ordinary public role/content messages from Inspect input."""
    pairs: list[tuple[str, str]] = []
    for message in messages:
        if message.role not in ("assistant", "user"):
            continue
        text = message.text
        if text and text.strip():
            pairs.append((message.role, text))
    return pairs


def _chat_message(role: str, content: str) -> ChatMessage:
    if role == "assistant":
        return ChatMessageAssistant(content=content, source="input")
    return ChatMessageUser(content=content, source="input")


def _public_conversation(runtime: LiveInterviewStore) -> list[ChatMessage]:
    """Build stakeholder input from the public ledger, never the sidecar."""
    return [
        _chat_message(message.role, message.content)
        for message in runtime.public_message_ledger
        if message.role in ("assistant", "user")
    ]


def _all_visible_knowledge(truth: BusinessProcessGraph) -> StakeholderKnowledge:
    """Construct a deterministic full-visibility knowledge input for a task."""
    node_properties: dict[str, tuple[NodeProperty, ...]] = {
        node_id: cast(
            tuple[NodeProperty, ...],
            ("activity", "actor", "system", "reads", "writes", "rationale"),
        )
        for node_id, node in truth.nodes.items()
        if not node.is_structural
    }
    edge_properties: dict[str, tuple[EdgeProperty, ...]] = {
        edge_id: ("condition",)
        for edge_id, edge in truth.edges.items()
        if not edge.is_structural
    }
    profile = StakeholderProfile(
        stakeholder_id="phase13-stakeholder",
        name="Phase 13 stakeholder",
        role="stakeholder",
        visible_node_ids=tuple(
            node_id for node_id, node in truth.nodes.items() if not node.is_structural
        ),
        visible_edge_ids=tuple(
            edge_id for edge_id, edge in truth.edges.items() if not edge.is_structural
        ),
        visible_node_attributes=node_properties,
        visible_edge_attributes=edge_properties,
    )
    return project_knowledge(truth, profile, seed=0)


def _resolve_setup(
    scenario_id: str | None,
    truth: BusinessProcessGraph | None,
    knowledge: StakeholderKnowledge | None,
) -> tuple[str, BusinessProcessGraph, StakeholderKnowledge]:
    if scenario_id is None:
        raise MultiTurnInterviewError("scenario_id is required")
    scenario = get_scenario(scenario_id) if truth is None else None
    resolved_truth = truth or (scenario.truth if scenario is not None else None)
    if resolved_truth is None:  # pragma: no cover - guarded by the branch above
        raise MultiTurnInterviewError("truth is required when scenario is unavailable")
    validate_canonical_graph(resolved_truth)
    resolved_knowledge = knowledge or _all_visible_knowledge(resolved_truth)
    validate_stakeholder_knowledge(resolved_knowledge)
    return scenario_id, resolved_truth, resolved_knowledge


def _persist(
    inspect_store: BusinessInterviewLiveStore,
    runtime: LiveInterviewStore,
    truth: BusinessProcessGraph,
    coverage: KnowledgeCoverageView,
) -> None:
    persist_live_state(inspect_store, runtime)
    persist_evaluation_inputs(inspect_store, truth, coverage)


@solver(name="multi_turn_interview_solver")
def multi_turn_interview_solver(
    scenario_id: str | None = None,
    stakeholder_knowledge: StakeholderKnowledge | None = None,
    *,
    truth: BusinessProcessGraph | None = None,
    max_turns: int = 8,
    initial_graph: AgentGraph | None = None,
    initial_messages: Sequence[ChatMessage] | None = None,
    max_turn_count: int | None = None,
) -> Solver:
    """Run candidate-question/stakeholder-response turns to explicit completion.

    The candidate is generated through Inspect's normal ``Generate`` solver
    callback, so its default/current model and durable tool-call handling are
    preserved.  Stakeholder calls use the existing required ``stakeholder``
    model role.  Private sidecar output is retained only in ``live_state``.
    """
    resolved_scenario_id, resolved_truth, resolved_knowledge = _resolve_setup(
        scenario_id,
        truth,
        stakeholder_knowledge,
    )
    catalog_initial_messages: tuple[ChatMessage, ...] | None = None
    if initial_messages is None and truth is None:
        catalog_initial_messages = tuple(
            _chat_message(message.role, message.content)
            for message in get_scenario(resolved_scenario_id).initial_messages
        )
    if max_turn_count is not None:
        max_turns = max_turn_count
    if max_turns < 1:
        raise ValueError("max_turns must be positive")
    coverage = knowledge_coverage_view(resolved_truth, resolved_knowledge)

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        inspect_store = state.store_as(BusinessInterviewLiveStore)
        if inspect_store.live_state:
            try:
                runtime = LiveInterviewStore.model_validate(inspect_store.live_state)
            except ValueError as exc:
                raise MultiTurnInterviewError(
                    "invalid persisted live interview state"
                ) from exc
        else:
            if initial_messages is not None:
                pairs = _public_pairs(initial_messages)
            elif catalog_initial_messages is not None:
                pairs = _public_pairs(catalog_initial_messages)
            else:
                # The Sample input is candidate task input, not implicitly a
                # stakeholder observation.  Custom callers can opt into
                # public initial history through initial_messages.
                pairs = []
            runtime = create_live_interview_store(
                resolved_scenario_id,
                initial_graph=initial_graph,
                initial_public_messages=pairs,
                max_turns=max_turns,
            )
        if runtime.scenario_id != resolved_scenario_id:
            raise MultiTurnInterviewError(
                f"live state scenario mismatch: {runtime.scenario_id!r}"
            )
        if runtime.max_turns != max_turns:
            raise MultiTurnInterviewError("live state max_turns mismatch")

        runtime_ref = [runtime]

        def persist(runtime_value: LiveInterviewStore) -> None:
            _persist(inspect_store, runtime_value, resolved_truth, coverage)

        def complete_state() -> None:
            state.completed = True

        if not any(
            isinstance(message, ChatMessageSystem)
            and _CANDIDATE_SYSTEM_MARKER in message.text
            for message in state.messages
        ):
            state.messages.insert(0, ChatMessageSystem(content=_CANDIDATE_SYSTEM))
        state.tools.extend(
            build_interview_tools(
                runtime_ref,
                persist=persist,
                on_complete=complete_state,
            )
        )
        persist(runtime_ref[0])

        while runtime_ref[0].active:
            runtime = runtime_ref[0]
            if runtime.candidate_turns >= runtime.max_turns:
                runtime = mark_max_turn_exhausted(runtime)
                runtime_ref[0] = runtime
                persist(runtime)
                break
            try:
                runtime = runtime.record_candidate_turn()
            except InterviewRuntimeError as exc:
                runtime = mark_max_turn_exhausted(runtime)
                runtime_ref[0] = runtime
                persist(runtime)
                state.metadata["interview_runtime_error"] = str(exc)
                break
            runtime_ref[0] = runtime
            persist(runtime)

            try:
                state = await generate(state, tool_calls="loop")
            except StakeholderResponseError:
                raise
            except Exception as exc:
                raise MultiTurnInterviewError("candidate model turn failed") from exc

            runtime = runtime_ref[0]
            if runtime.completed or runtime.incomplete:
                break
            question = state.output.message.text.strip()
            if not question:
                runtime = mark_max_turn_exhausted(
                    runtime, "candidate_did_not_ask_question"
                )
                runtime_ref[0] = runtime
                persist(runtime)
                break
            try:
                runtime = runtime.record_candidate_question(question)
                runtime_ref[0] = runtime
                persist(runtime)
                stakeholder_turn = await invoke_stakeholder_response_with_plan(
                    _public_conversation(runtime),
                    resolved_knowledge,
                    prior_ledger=runtime.semantic_ledger,
                )
                runtime = runtime.ingest_stakeholder_response(
                    resolved_knowledge,
                    stakeholder_turn.plan,
                    stakeholder_turn.response,
                )
            except Exception:
                # Do not append a public message when sidecar validation or
                # stakeholder generation failed.  The exception remains
                # visible to Inspect as a provider/runtime failure.
                raise
            runtime_ref[0] = runtime
            persist(runtime)
            state.messages.append(
                ChatMessageUser(
                    content=stakeholder_turn.response.message, source="input"
                )
            )

            # A question emitted on the final allowed candidate turn receives
            # its one response, then terminates as incomplete unless the Agent
            # had explicitly called complete_interview in that turn.
            if runtime.candidate_turns >= runtime.max_turns:
                runtime = mark_max_turn_exhausted(runtime)
                runtime_ref[0] = runtime
                persist(runtime)
                break

        runtime = runtime_ref[0]
        persist(runtime)
        state.completed = True
        state.metadata["interview_status"] = runtime.protocol_state.status
        if runtime.incomplete:
            state.metadata["interview_runtime_error"] = (
                runtime.protocol_state.failure_reason or "incomplete interview"
            )
        state.metadata["interview_candidate_turns"] = runtime.candidate_turns
        state.metadata["interview_stakeholder_turns"] = runtime.stakeholder_turns
        return state

    return solve


# Concise factory aliases for callers that do not use the registered name.
phase13_solver = multi_turn_interview_solver
multi_turn_solver = multi_turn_interview_solver


def phase13_interview_task(
    scenario_id: str = "lab_sample_flow",
    stakeholder_knowledge: StakeholderKnowledge | None = None,
    *,
    truth: BusinessProcessGraph | None = None,
    max_turns: int = 8,
    initial_graph: AgentGraph | None = None,
    initial_messages: Sequence[ChatMessage] | None = None,
    max_turn_count: int | None = None,
) -> Task:
    """Build a real Inspect Task for deterministic MockLLM integration tests.

    Tests can pass ``model="mockllm/candidate"`` to ``inspect_eval`` and a
    custom ``model_roles={"stakeholder": get_model(...)}``; no private state is
    placed in the Sample input or candidate system message.
    """
    resolved_scenario_id, resolved_truth, resolved_knowledge = _resolve_setup(
        scenario_id,
        truth,
        stakeholder_knowledge,
    )
    if initial_messages is not None:
        initial = list(initial_messages)
    else:
        try:
            scenario = get_scenario(resolved_scenario_id)
        except LookupError:
            if truth is None:
                raise
            initial = []
        else:
            initial = [
                _chat_message(message.role, message.content)
                for message in scenario.initial_messages
            ]
    sample_id = f"phase13-{resolved_scenario_id}"
    if max_turn_count is not None:
        max_turns = max_turn_count
    return Task(
        dataset=MemoryDataset(
            [
                Sample(
                    id=sample_id,
                    input=initial,
                    metadata={"scenario_id": resolved_scenario_id},
                )
            ]
        ),
        solver=multi_turn_interview_solver(
            resolved_scenario_id,
            resolved_knowledge,
            truth=resolved_truth,
            max_turns=max_turns,
            initial_graph=initial_graph,
            initial_messages=initial,
        ),
        scorer=phase13_primary_scorer(),
        model=None,
        version=1,
    )


@task(name="phase13_interview")
def phase13_interview() -> Task:
    """Registered Phase 13 task; supply candidate/stakeholder models at eval time."""
    return phase13_interview_task()


__all__ = [
    "MultiTurnInterviewError",
    "multi_turn_interview_solver",
    "multi_turn_solver",
    "phase13_interview",
    "phase13_interview_task",
    "phase13_solver",
]
