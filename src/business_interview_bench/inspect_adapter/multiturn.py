"""Inspect solver for the Phase 13 multi-turn interview vertical slice."""

# The workspace-level auxiliary resolver may not see the Inspect dev group.
# Project-level ``uv run pyright`` is authoritative for this adapter.
# pyright: reportMissingImports=false

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, cast

from inspect_ai import Task, task
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageUser,
    GenerateConfig,
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
from business_interview.scenarios import StakeholderPrompt, get_scenario
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
    StakeholderAttemptDiagnostics,
    StakeholderResponseError,
    invoke_stakeholder_response_with_plan,
)
from .tools import build_interview_tools

_DEFAULT_MAX_CANDIDATE_STEPS_PER_TURN = 8
_DEFAULT_CANDIDATE_MAX_TOKENS = 1024
_DEFAULT_STAKEHOLDER_GENERATIONS_PER_TURN = 6

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


def build_full_visibility_knowledge_for_smoke(
    truth: BusinessProcessGraph,
) -> StakeholderKnowledge:
    """Build full visibility explicitly for infrastructure smoke tests only.

    This helper is intentionally not used by the live Phase 13 task.  Live
    callers must pass exact knowledge or an explicit profile plus seed.
    """
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


def _resolve_max_turns(
    max_turns: int,
    max_turn_count: int | None,
    max_interview_turns: int | None,
) -> int:
    aliases = [
        value for value in (max_turn_count, max_interview_turns) if value is not None
    ]
    if len(set(aliases)) > 1:
        raise ValueError("max_turn_count and max_interview_turns must agree")
    return aliases[0] if aliases else max_turns


def _validate_candidate_limits(
    max_turns: int,
    max_candidate_steps_per_turn: int,
    candidate_max_tokens: int,
) -> None:
    if max_turns < 1:
        raise ValueError("max_interview_turns must be positive")
    if max_candidate_steps_per_turn < 1:
        raise ValueError("max_candidate_steps_per_turn must be positive")
    if candidate_max_tokens < 1:
        raise ValueError("candidate_max_tokens must be positive")


def _coerce_stakeholder_profile(
    value: StakeholderProfile | Mapping[str, object] | None,
) -> StakeholderProfile | None:
    """Convert JSON/YAML task configuration into the core profile model."""
    if value is None or isinstance(value, StakeholderProfile):
        return value
    try:
        return StakeholderProfile.model_validate(value)
    except ValueError as exc:
        raise MultiTurnInterviewError(
            f"invalid stakeholder_profile configuration: {exc}"
        ) from exc


def _resolve_setup(
    scenario_id: str | None,
    truth: BusinessProcessGraph | None,
    knowledge: StakeholderKnowledge | None,
    *,
    stakeholder_profile: StakeholderProfile | None = None,
    stakeholder_seed: int | None = None,
    stakeholder_prompt: StakeholderPrompt | str | None = None,
) -> tuple[
    str,
    BusinessProcessGraph,
    StakeholderKnowledge,
    StakeholderProfile | None,
    int | None,
    StakeholderPrompt | str | None,
]:
    if scenario_id is None:
        raise MultiTurnInterviewError("scenario_id is required")
    try:
        scenario = get_scenario(scenario_id)
    except LookupError:
        if truth is None:
            raise
        scenario = None
    resolved_truth = truth or (scenario.truth if scenario is not None else None)
    if resolved_truth is None:  # pragma: no cover - guarded by the branch above
        raise MultiTurnInterviewError("truth is required when scenario is unavailable")
    validate_canonical_graph(resolved_truth)

    if knowledge is None:
        if stakeholder_profile is None or stakeholder_seed is None:
            raise MultiTurnInterviewError(
                "stakeholder setup is required: pass exact stakeholder_knowledge "
                "or both stakeholder_profile and stakeholder_seed"
            )
        resolved_knowledge = project_knowledge(
            resolved_truth,
            stakeholder_profile,
            seed=stakeholder_seed,
        )
    else:
        # A task factory may pass the already projected exact object together
        # with its profile/seed to persist reproducibility metadata. Validate
        # that provenance now, while live construction still owns projection;
        # the offline scorer deliberately does not repeat this check.
        if stakeholder_profile is not None:
            if stakeholder_seed is None:
                raise MultiTurnInterviewError(
                    "stakeholder_seed is required when stakeholder_profile is supplied"
                )
            projected = project_knowledge(
                resolved_truth,
                stakeholder_profile,
                seed=stakeholder_seed,
            )
            if projected != knowledge:
                raise MultiTurnInterviewError(
                    "stakeholder_knowledge does not match stakeholder_profile "
                    "and stakeholder_seed"
                )
        resolved_knowledge = knowledge
    validate_stakeholder_knowledge(resolved_knowledge)

    resolved_prompt = stakeholder_prompt
    if resolved_prompt is None and scenario is not None:
        resolved_prompt = scenario.prompt
    if resolved_prompt is None:
        raise MultiTurnInterviewError(
            "stakeholder_prompt is required when scenario is unavailable"
        )
    if isinstance(resolved_prompt, str) and not resolved_prompt.strip():
        raise MultiTurnInterviewError("stakeholder_prompt must not be blank")
    resolved_seed = (
        stakeholder_seed
        if stakeholder_seed is not None
        else resolved_knowledge.generation_seed
    )
    return (
        scenario_id,
        resolved_truth,
        resolved_knowledge,
        stakeholder_profile,
        resolved_seed,
        resolved_prompt,
    )


def _persist(
    inspect_store: BusinessInterviewLiveStore,
    runtime: LiveInterviewStore,
    truth: BusinessProcessGraph,
    coverage: KnowledgeCoverageView,
    knowledge: StakeholderKnowledge,
    stakeholder_profile: StakeholderProfile | None,
    stakeholder_seed: int | None,
) -> None:
    persist_live_state(inspect_store, runtime)
    persist_evaluation_inputs(
        inspect_store,
        truth,
        coverage,
        stakeholder_knowledge=knowledge,
        stakeholder_profile=stakeholder_profile,
        stakeholder_seed=stakeholder_seed,
    )


@solver(name="multi_turn_interview_solver")
def multi_turn_interview_solver(
    scenario_id: str | None = None,
    stakeholder_knowledge: StakeholderKnowledge | None = None,
    *,
    truth: BusinessProcessGraph | None = None,
    stakeholder_profile: StakeholderProfile | None = None,
    stakeholder_seed: int | None = None,
    stakeholder_prompt: StakeholderPrompt | str | None = None,
    max_turns: int = 8,
    max_interview_turns: int | None = None,
    max_candidate_steps_per_turn: int = _DEFAULT_MAX_CANDIDATE_STEPS_PER_TURN,
    candidate_max_tokens: int = _DEFAULT_CANDIDATE_MAX_TOKENS,
    initial_graph: AgentGraph | None = None,
    initial_messages: Sequence[ChatMessage] | None = None,
    max_turn_count: int | None = None,
) -> Solver:
    """Run candidate-question/stakeholder-response turns to explicit completion.

    The candidate is generated through Inspect's normal ``Generate`` solver
    callback, so its default/current model and durable tool-call handling are
    preserved.  Stakeholder calls use the existing required ``stakeholder``
    model role.  ``max_candidate_steps_per_turn`` counts candidate model
    generations, including tool-producing and question-producing calls.
    Private sidecar output is retained only in ``live_state``.
    """
    (
        resolved_scenario_id,
        resolved_truth,
        resolved_knowledge,
        resolved_profile,
        resolved_seed,
        resolved_prompt,
    ) = _resolve_setup(
        scenario_id,
        truth,
        stakeholder_knowledge,
        stakeholder_profile=stakeholder_profile,
        stakeholder_seed=stakeholder_seed,
        stakeholder_prompt=stakeholder_prompt,
    )
    catalog_initial_messages: tuple[ChatMessage, ...] | None = None
    if initial_messages is None and truth is None:
        catalog_initial_messages = tuple(
            _chat_message(message.role, message.content)
            for message in get_scenario(resolved_scenario_id).initial_messages
        )
    max_turns = _resolve_max_turns(
        max_turns,
        max_turn_count,
        max_interview_turns,
    )
    _validate_candidate_limits(
        max_turns,
        max_candidate_steps_per_turn,
        candidate_max_tokens,
    )
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
                max_candidate_steps_per_turn=max_candidate_steps_per_turn,
            )
        if runtime.scenario_id != resolved_scenario_id:
            raise MultiTurnInterviewError(
                f"live state scenario mismatch: {runtime.scenario_id!r}"
            )
        if runtime.max_turns != max_turns:
            raise MultiTurnInterviewError("live state max_turns mismatch")
        if runtime.max_candidate_steps_per_turn != max_candidate_steps_per_turn:
            raise MultiTurnInterviewError(
                "live state max_candidate_steps_per_turn mismatch"
            )

        runtime_ref = [runtime]

        def persist(runtime_value: LiveInterviewStore) -> None:
            _persist(
                inspect_store,
                runtime_value,
                resolved_truth,
                coverage,
                resolved_knowledge,
                resolved_profile,
                resolved_seed,
            )

        def complete_state() -> None:
            state.completed = True

        def record_stakeholder_diagnostics(
            diagnostics: StakeholderAttemptDiagnostics | None,
        ) -> None:
            if diagnostics is None:
                return
            for name, value in diagnostics.as_dict().items():
                key = f"interview_stakeholder_{name}"
                previous = state.metadata.get(key)
                previous_count = previous if isinstance(previous, int) else 0
                state.metadata[key] = previous_count + value

        def record_stakeholder_failure(error: StakeholderResponseError) -> None:
            state.metadata["interview_stakeholder_failure_kind"] = (
                error.failure_kind or "provider"
            )
            state.metadata["interview_stakeholder_failure_phase"] = error.phase
            state.metadata["interview_stakeholder_failure_reason"] = (
                error.failure_reason or "stakeholder_response_failure"
            )
            state.metadata["interview_stakeholder_retry_exhausted"] = (
                error.retry_exhausted
            )
            record_stakeholder_diagnostics(error.diagnostics)

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

            question: str | None = None
            while runtime_ref[0].active:
                if runtime_ref[0].candidate_steps >= max_candidate_steps_per_turn:
                    runtime = mark_max_turn_exhausted(
                        runtime_ref[0],
                        "candidate_step_limit_exhausted",
                    )
                    runtime_ref[0] = runtime
                    persist(runtime)
                    break
                try:
                    # Count the model generation before calling Inspect. This
                    # makes candidate_steps mean exactly one candidate model
                    # invocation, whether it emits tools or a question.
                    runtime = runtime_ref[0].record_candidate_step()
                except InterviewRuntimeError:
                    runtime = mark_max_turn_exhausted(
                        runtime_ref[0],
                        "candidate_step_limit_exhausted",
                    )
                    runtime_ref[0] = runtime
                    persist(runtime)
                    break
                runtime_ref[0] = runtime
                persist(runtime)
                try:
                    # Inspect's ``loop`` is intentionally not used here: it
                    # can keep invoking the candidate until a provider stops
                    # emitting tools. One explicit ``single`` call is one
                    # bounded candidate model generation.
                    state = await generate(
                        state,
                        tool_calls="single",
                        max_tokens=candidate_max_tokens,
                        parallel_tool_calls=False,
                    )
                except StakeholderResponseError:
                    raise
                except Exception as exc:
                    raise MultiTurnInterviewError(
                        "candidate model turn failed"
                    ) from exc

                runtime = runtime_ref[0]
                tool_calls = state.output.message.tool_calls or []
                if tool_calls:
                    # Tool-only output is not a public question. Generate the
                    # next candidate generation within this same interview
                    # turn, unless a terminal tool already completed it.
                    persist(runtime)
                    if runtime.completed or runtime.incomplete:
                        break
                    continue
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

            runtime = runtime_ref[0]
            if runtime.completed or runtime.incomplete:
                break
            if question is None:
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
                    stakeholder_prompt=resolved_prompt,
                    prior_ledger=runtime.semantic_ledger,
                )
                runtime = runtime.ingest_stakeholder_response(
                    resolved_knowledge,
                    stakeholder_turn.plan,
                    stakeholder_turn.response,
                )
            except Exception as exc:
                if isinstance(exc, StakeholderResponseError):
                    # A bounded WHAT/HOW failure is an authoritative terminal
                    # protocol outcome.  Do not append a fabricated public
                    # answer; persist an explicit incomplete state and retain
                    # only safe failure counters in Inspect metadata.
                    record_stakeholder_failure(exc)
                    failure_reason = exc.failure_reason
                    if failure_reason is None:
                        failure_reason = "stakeholder_response_failure"
                    runtime = mark_max_turn_exhausted(runtime, failure_reason)
                    runtime_ref[0] = runtime
                    persist(runtime)
                    break
                raise
            record_stakeholder_diagnostics(stakeholder_turn.diagnostics)
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
        state.metadata["interview_candidate_steps"] = runtime.candidate_steps
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
    stakeholder_profile: StakeholderProfile | None = None,
    stakeholder_seed: int | None = None,
    stakeholder_prompt: StakeholderPrompt | str | None = None,
    max_turns: int = 8,
    max_interview_turns: int | None = None,
    max_candidate_steps_per_turn: int = _DEFAULT_MAX_CANDIDATE_STEPS_PER_TURN,
    candidate_max_tokens: int = _DEFAULT_CANDIDATE_MAX_TOKENS,
    run_index: int | None = None,
    initial_graph: AgentGraph | None = None,
    initial_messages: Sequence[ChatMessage] | None = None,
    max_turn_count: int | None = None,
) -> Task:
    """Build a real Inspect Task for live runs and MockLLM integration tests.

    ``max_candidate_steps_per_turn`` is the maximum number of candidate model
    generations allowed within one interview turn. Callers can pass
    ``model="mockllm/candidate"`` to ``inspect_eval`` and a
    custom ``model_roles={"stakeholder": get_model(...)}``; no private state is
    placed in the Sample input or candidate system message.
    """
    (
        resolved_scenario_id,
        resolved_truth,
        resolved_knowledge,
        resolved_profile,
        resolved_seed,
        resolved_prompt,
    ) = _resolve_setup(
        scenario_id,
        truth,
        stakeholder_knowledge,
        stakeholder_profile=stakeholder_profile,
        stakeholder_seed=stakeholder_seed,
        stakeholder_prompt=stakeholder_prompt,
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
    max_turns = _resolve_max_turns(
        max_turns,
        max_turn_count,
        max_interview_turns,
    )
    _validate_candidate_limits(
        max_turns,
        max_candidate_steps_per_turn,
        candidate_max_tokens,
    )
    if run_index is not None and run_index < 0:
        raise MultiTurnInterviewError("run_index must be non-negative")
    sample_metadata: dict[str, Any] = {
        "scenario_id": resolved_scenario_id,
        "phase13_max_interview_turns": max_turns,
        "phase13_max_candidate_steps_per_turn": max_candidate_steps_per_turn,
        "phase13_candidate_max_tokens": candidate_max_tokens,
    }
    if run_index is not None:
        sample_metadata["phase14_run_index"] = run_index
    # Leave one message of headroom because Inspect checks the limit before a
    # generation. Each tool-producing generation contributes assistant+tool
    # messages; a question-producing generation contributes assistant+
    # stakeholder.
    message_limit = (
        len(initial) + max_turns * (2 * max_candidate_steps_per_turn + 2) + 1
    )
    token_limit = max(32_000, message_limit * candidate_max_tokens * 4)
    turn_limit = (
        max_turns
        * (max_candidate_steps_per_turn + _DEFAULT_STAKEHOLDER_GENERATIONS_PER_TURN + 1)
        + 1
    )
    return Task(
        dataset=MemoryDataset(
            [
                Sample(
                    id=sample_id,
                    input=initial,
                    metadata=sample_metadata,
                )
            ]
        ),
        solver=multi_turn_interview_solver(
            resolved_scenario_id,
            resolved_knowledge,
            truth=resolved_truth,
            stakeholder_profile=resolved_profile,
            stakeholder_seed=resolved_seed,
            stakeholder_prompt=resolved_prompt,
            max_turns=max_turns,
            max_candidate_steps_per_turn=max_candidate_steps_per_turn,
            candidate_max_tokens=candidate_max_tokens,
            initial_graph=initial_graph,
            initial_messages=initial,
        ),
        scorer=phase13_primary_scorer(),
        model=None,
        config=GenerateConfig(max_tokens=candidate_max_tokens),
        message_limit=message_limit,
        token_limit=token_limit,
        turn_limit=turn_limit,
        version=2,
    )


def phase13_smoke_interview_task(
    scenario_id: str = "lab_sample_flow",
    *,
    truth: BusinessProcessGraph | None = None,
    max_turns: int = 8,
    max_candidate_steps_per_turn: int = _DEFAULT_MAX_CANDIDATE_STEPS_PER_TURN,
    candidate_max_tokens: int = _DEFAULT_CANDIDATE_MAX_TOKENS,
) -> Task:
    """Build an explicit full-visibility task for adapter infrastructure smoke tests."""
    if truth is None:
        truth = get_scenario(scenario_id).truth
    knowledge = build_full_visibility_knowledge_for_smoke(truth)
    return phase13_interview_task(
        scenario_id,
        knowledge,
        truth=truth,
        max_turns=max_turns,
        max_candidate_steps_per_turn=max_candidate_steps_per_turn,
        candidate_max_tokens=candidate_max_tokens,
    )


@task(name="phase13_interview")
def phase13_interview(
    scenario_id: str = "lab_sample_flow",
    stakeholder_profile: StakeholderProfile | Mapping[str, object] | None = None,
    stakeholder_seed: int | None = None,
    max_turns: int = 8,
    max_interview_turns: int | None = None,
    max_candidate_steps_per_turn: int = _DEFAULT_MAX_CANDIDATE_STEPS_PER_TURN,
    candidate_max_tokens: int = _DEFAULT_CANDIDATE_MAX_TOKENS,
    run_index: int = 0,
) -> Task:
    """Build the registered live task from public profile/seed config.

    Inspect CLI/task-config supplies ``stakeholder_profile`` as a plain JSON or
    YAML mapping. Exact knowledge remains a programmatic-factory capability;
    this registered contract keeps large private knowledge out of task args.
    """
    return phase13_interview_task(
        scenario_id=scenario_id,
        stakeholder_profile=_coerce_stakeholder_profile(stakeholder_profile),
        stakeholder_seed=stakeholder_seed,
        max_turns=max_turns,
        max_interview_turns=max_interview_turns,
        max_candidate_steps_per_turn=max_candidate_steps_per_turn,
        candidate_max_tokens=candidate_max_tokens,
        run_index=run_index,
    )


__all__ = [
    "build_full_visibility_knowledge_for_smoke",
    "MultiTurnInterviewError",
    "multi_turn_interview_solver",
    "multi_turn_solver",
    "phase13_interview",
    "phase13_interview_task",
    "phase13_smoke_interview_task",
    "phase13_solver",
]
