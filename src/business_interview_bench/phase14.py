"""Phase 14 experiment configuration and Inspect ``.eval`` diagnostics.

This is an Inspect-side analysis layer. It never calls a model, reruns
stakeholder projection while reading a log, or changes the core 41-field
evaluator contract. Logged exact stakeholder knowledge remains an opaque
historical input; summaries expose only safe provenance identifiers and
score/usage diagnostics.
"""

# pyright: reportMissingImports=false

from __future__ import annotations

import argparse
import json
import os
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import fields
from pathlib import Path
from typing import Any

from inspect_ai.log import EvalLog, read_eval_log
from inspect_ai.model import GenerateConfig
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from business_interview.evaluation import PrimaryEvaluation
from business_interview.scenarios import get_scenario
from business_interview.stakeholders import StakeholderProfile, project_knowledge

SUMMARY_SCHEMA_VERSION = 2
_USAGE_FIELDS = ("input_tokens", "output_tokens", "total_tokens", "total_cost")
# Keep the run-config renderer aligned with the installed Inspect schema rather
# than maintaining a second, incomplete list of GenerateConfig fields.
_GENERATION_FIELDS = frozenset(GenerateConfig.model_fields)
# These fields can carry credentials or private prompt material and are not
# allowed in the Phase 14 launch artifact or safe summaries.
_SENSITIVE_GENERATION_FIELDS = {"extra_headers", "extra_body", "system_message"}
_SAFE_GENERATION_FIELDS = _GENERATION_FIELDS - _SENSITIVE_GENERATION_FIELDS
_PRIMARY_FIELDS = tuple(item.name for item in fields(PrimaryEvaluation))
_MODEL_PLACEHOLDER = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_PLAN_PROMPT_MARKER = "choose only the semantic assertions"
_REALIZATION_PROMPT_MARKER = "validated private plan:"
_RETRY_PROMPT_MARKER = "previous output rejected:"
_PHASE14_TASK = "business_interview_bench/phase13_interview"


class Phase14RunConfig(BaseModel):
    """One reproducible Phase 14 run description.

    Model names may be environment-expanded by the operator or launch script;
    credentials are intentionally absent from this model and config files.
    """

    model_config = ConfigDict(extra="forbid")

    scenario_id: str = Field(min_length=1)
    candidate_model: str = Field(min_length=1)
    stakeholder_model: str = Field(min_length=1)
    stakeholder_profile: StakeholderProfile
    stakeholder_seed: int
    max_interview_turns: int = Field(default=8, ge=1)
    max_candidate_steps_per_turn: int = Field(default=8, ge=1)
    candidate_max_tokens: int = Field(default=1024, ge=1)
    candidate_generation: dict[str, Any] = Field(default_factory=dict)
    stakeholder_generation: dict[str, Any] = Field(default_factory=dict)
    epoch: int = Field(default=1, ge=1)
    run_index: int = Field(default=0, ge=0)


class Phase14ExperimentConfig(BaseModel):
    """Small, explicit calibration set suitable for Inspect run-config use."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="phase14-calibration", min_length=1)
    schema_version: int = Field(default=1, ge=1)
    runs: list[Phase14RunConfig] = Field(min_length=1)


def _resolve_environment_placeholders(value: str, *, field_name: str) -> str:
    """Resolve ``${VAR}`` model names without ever passing them to a provider."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty model name")

    def replace(match: re.Match[str]) -> str:
        variable = match.group(1)
        resolved = os.environ.get(variable)
        if resolved is None or not resolved.strip():
            raise ValueError(
                f"missing required environment variable {variable} for {field_name}"
            )
        return resolved.strip()

    rendered = _MODEL_PLACEHOLDER.sub(replace, value).strip()
    if "${" in rendered:
        raise ValueError(f"unresolved environment placeholder in {field_name}")
    if not rendered:
        raise ValueError(f"{field_name} resolved to an empty model name")
    return rendered


def _validated_generation_config(
    value: Mapping[str, Any] | dict[str, Any], *, field_name: str
) -> dict[str, Any]:
    """Validate and JSON-render one Inspect ``GenerateConfig`` mapping."""
    payload = dict(value)
    unknown = sorted(set(payload) - _GENERATION_FIELDS)
    if unknown:
        raise ValueError(
            f"{field_name} contains unsupported GenerateConfig fields: "
            f"{', '.join(unknown)}"
        )
    sensitive = sorted(_SENSITIVE_GENERATION_FIELDS.intersection(payload))
    if sensitive:
        fields_text = ", ".join(sensitive)
        raise ValueError(
            f"{field_name} must not contain {fields_text}; use provider environment "
            "configuration so credentials are not saved in the run config"
        )
    try:
        config = GenerateConfig.model_validate(payload)
    except (TypeError, ValueError, ValidationError) as exc:
        raise ValueError(f"invalid {field_name} GenerateConfig: {exc}") from exc
    return config.model_dump(mode="json", exclude_none=True)


def build_inspect_run_config(run: Phase14RunConfig) -> dict[str, Any]:
    """Build one complete, reproducible Inspect ``--run-config`` document.

    The candidate's runtime token bound deliberately stays in task arguments;
    the optional GenerateConfig ``max_tokens`` value must agree with it when
    supplied.  Stakeholder knowledge is never part of this launch artifact.
    """
    candidate_model = _resolve_environment_placeholders(
        run.candidate_model, field_name="candidate_model"
    )
    stakeholder_model = _resolve_environment_placeholders(
        run.stakeholder_model, field_name="stakeholder_model"
    )
    candidate_generation = _validated_generation_config(
        run.candidate_generation,
        field_name="candidate_generation",
    )
    stakeholder_generation = _validated_generation_config(
        run.stakeholder_generation,
        field_name="stakeholder_generation",
    )
    configured_max_tokens = candidate_generation.get("max_tokens")
    if (
        configured_max_tokens is not None
        and configured_max_tokens != run.candidate_max_tokens
    ):
        raise ValueError(
            "candidate_generation.max_tokens must equal candidate_max_tokens "
            f"({run.candidate_max_tokens})"
        )

    return {
        "task": {
            "task": _PHASE14_TASK,
            "args": build_inspect_task_config(run),
        },
        "model": {"model": candidate_model},
        "model_roles": {
            "stakeholder": {
                "model": stakeholder_model,
                "config": stakeholder_generation,
            }
        },
        "generate_config": candidate_generation,
        "eval_config": {"epochs": run.epoch},
    }


def build_inspect_task_config(run: Phase14RunConfig) -> dict[str, Any]:
    """Return only arguments accepted by the registered Phase 13 task.

    Model names and generation settings stay in the experiment manifest and
    are applied by the Inspect CLI invocation, not leaked into task-private
    Store state or copied into candidate messages.
    """
    return {
        "scenario_id": run.scenario_id,
        "stakeholder_profile": run.stakeholder_profile.model_dump(mode="json"),
        "stakeholder_seed": run.stakeholder_seed,
        "max_interview_turns": run.max_interview_turns,
        "max_candidate_steps_per_turn": run.max_candidate_steps_per_turn,
        "candidate_max_tokens": run.candidate_max_tokens,
        "run_index": run.run_index,
    }


def validate_experiment_config(
    config: Phase14ExperimentConfig,
) -> Phase14ExperimentConfig:
    """Validate scenario/profile compatibility during live configuration.

    This is intentionally a construction-time check. The historical scorer
    never calls ``project_knowledge``.
    """
    for index, run in enumerate(config.runs):
        try:
            scenario = get_scenario(run.scenario_id)
            project_knowledge(
                scenario.truth,
                run.stakeholder_profile,
                seed=run.stakeholder_seed,
            )
        except (LookupError, ValueError) as exc:
            raise ValueError(
                f"invalid Phase 14 run configuration at index {index}: "
                f"{run.scenario_id}"
            ) from exc
    return config


def load_experiment_config(path: str | Path) -> Phase14ExperimentConfig:
    """Load and validate a JSON Phase 14 experiment configuration."""
    config_path = Path(path)
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
        config = Phase14ExperimentConfig.model_validate(raw)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise ValueError(f"invalid Phase 14 experiment config: {config_path}") from exc
    return validate_experiment_config(config)


def _as_mapping(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(mode="json")
        if isinstance(dumped, Mapping):
            return dict(dumped)
    return {}


def _store_field(store: object, field: str) -> object:
    values = _as_mapping(store)
    exact_key = f"BusinessInterviewLiveStore:{field}"
    if exact_key in values:
        return values[exact_key]
    matches = [
        (str(key), value)
        for key, value in values.items()
        if str(key).endswith(f":{field}")
    ]
    return matches[-1][1] if matches else None


def _runtime_payload(sample: object) -> dict[str, Any]:
    return _as_mapping(_store_field(getattr(sample, "store", None), "live_state"))


def _sample_metadata(sample: object) -> dict[str, Any]:
    return _as_mapping(getattr(sample, "metadata", None))


def _task_args(log: EvalLog) -> dict[str, Any]:
    return _as_mapping(getattr(log.eval, "task_args_passed", None))


def _int_or_none(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    return value if isinstance(value, int) else None


def _numeric_or_none(value: object) -> int | float | None:
    if isinstance(value, bool):
        return None
    return value if isinstance(value, (int, float)) else None


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def _events(sample: object) -> list[object]:
    events = getattr(sample, "events", None)
    if isinstance(events, Sequence) and not isinstance(events, str):
        return list(events)
    return []


def _is_model_event(event: object) -> bool:
    return type(event).__name__ == "ModelEvent"


def _event_completion(event: object) -> str:
    output = getattr(event, "output", None)
    completion = getattr(output, "completion", None)
    if isinstance(completion, str):
        return completion
    return _text(_as_mapping(output).get("completion"))


def _event_error(event: object) -> str:
    error = getattr(event, "error", None)
    if error is None:
        # Content-moderation refusals can be represented on ModelOutput rather
        # than on ModelEvent by Inspect providers.
        error = getattr(getattr(event, "output", None), "error", None)
    if error is None:
        return ""
    return error if isinstance(error, str) else str(error)


def _model_name(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    payload = _as_mapping(value)
    model = payload.get("model")
    if isinstance(model, str) and model:
        return model
    model_attr = getattr(value, "model", None)
    return model_attr if isinstance(model_attr, str) and model_attr else None


def _model_names(log: EvalLog, sample: object) -> tuple[str | None, str | None]:
    candidate_model = _model_name(getattr(log.eval, "model", None))
    stakeholder_model: str | None = None
    roles = _as_mapping(getattr(log.eval, "model_roles", None))
    role_config = roles.get("stakeholder")
    if role_config is not None:
        stakeholder_model = _model_name(role_config)
        if stakeholder_model is None:
            stakeholder_model = _model_name(_as_mapping(role_config).get("model"))

    for event in _events(sample):
        if not _is_model_event(event):
            continue
        event_model = _model_name(getattr(event, "model", None))
        if getattr(event, "role", None) == "stakeholder":
            stakeholder_model = stakeholder_model or event_model
        else:
            candidate_model = candidate_model or event_model
    return candidate_model, stakeholder_model


def _safe_generation_config(value: object) -> dict[str, Any]:
    payload = _as_mapping(value)
    return {
        key: payload[key]
        for key in _SAFE_GENERATION_FIELDS
        if key in payload and payload[key] is not None
    }


def _merged_generation_config(values: Iterable[object]) -> dict[str, Any]:
    config: dict[str, Any] = {}
    for value in values:
        config.update(_safe_generation_config(value))
    return config


def _generation_parameters(
    log: EvalLog, sample: object | None = None
) -> dict[str, dict[str, Any]]:
    plan = getattr(log, "plan", None)
    candidate = _merged_generation_config(
        (
            getattr(log.eval, "model_generate_config", None),
            getattr(plan, "config", None),
        )
    )
    if not candidate:
        candidate = _merged_generation_config(
            getattr(event, "config", None)
            for event in _events(sample)
            if _is_model_event(event) and getattr(event, "role", None) != "stakeholder"
        )
    stakeholder: dict[str, Any] = {}
    roles = _as_mapping(getattr(log.eval, "model_roles", None))
    role_config = roles.get("stakeholder")
    if role_config is not None:
        role_payload = _as_mapping(role_config)
        stakeholder = _safe_generation_config(role_payload.get("config", role_config))
    if not stakeholder:
        stakeholder = _merged_generation_config(
            getattr(event, "config", None)
            for event in _events(sample)
            if _is_model_event(event) and getattr(event, "role", None) == "stakeholder"
        )
    return {"candidate": candidate, "stakeholder": stakeholder}


def _empty_usage() -> dict[str, Any]:
    return {field: None for field in _USAGE_FIELDS}


def _usage(value: object) -> dict[str, Any]:
    payload = _as_mapping(value)
    return {field: _numeric_or_none(payload.get(field)) for field in _USAGE_FIELDS}


def _sum_usage(values: Sequence[dict[str, Any]]) -> dict[str, Any]:
    if not values:
        return _empty_usage()
    result: dict[str, Any] = {}
    for field in _USAGE_FIELDS:
        present = [value[field] for value in values if value[field] is not None]
        result[field] = sum(present) if len(present) == len(values) else None
    return result


def _event_usages(sample: object, *, stakeholder: bool) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for event in _events(sample):
        if not _is_model_event(event):
            continue
        is_stakeholder = getattr(event, "role", None) == "stakeholder"
        if is_stakeholder != stakeholder:
            continue
        output = getattr(event, "output", None)
        output_payload = _as_mapping(output)
        output_usage = getattr(output, "usage", None)
        values.append(_usage(output_usage or output_payload.get("usage")))
    return values


def _subtract_usage(
    total: dict[str, Any], stakeholder: dict[str, Any]
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for field in _USAGE_FIELDS:
        left = total[field]
        right = stakeholder[field]
        result[field] = left - right if left is not None and right is not None else None
    return result


def _usage_by_role(
    sample: object,
    candidate_model: str | None,
    stakeholder_model: str | None,
) -> dict[str, dict[str, Any]]:
    model_usage = _as_mapping(getattr(sample, "model_usage", None))
    role_usage = _as_mapping(getattr(sample, "role_usage", None))
    candidate_event_usage = _event_usages(sample, stakeholder=False)
    candidate = (
        _sum_usage(candidate_event_usage) if candidate_event_usage else _empty_usage()
    )
    if "stakeholder" in role_usage:
        stakeholder = _usage(role_usage["stakeholder"])
    else:
        stakeholder_event_usage = _event_usages(sample, stakeholder=True)
        stakeholder = (
            _sum_usage(stakeholder_event_usage)
            if stakeholder_event_usage
            else (
                _usage(model_usage[stakeholder_model])
                if stakeholder_model is not None and stakeholder_model in model_usage
                else _empty_usage()
            )
        )
    if not candidate_event_usage and candidate_model is not None:
        if candidate_model in model_usage:
            candidate_total = _usage(model_usage[candidate_model])
            candidate = (
                _subtract_usage(candidate_total, stakeholder)
                if candidate_model == stakeholder_model
                else candidate_total
            )
    total = (
        _sum_usage([_usage(value) for value in model_usage.values()])
        if model_usage
        else _sum_usage([candidate, stakeholder])
    )
    return {"candidate": candidate, "stakeholder": stakeholder, "total": total}


def _score_value(sample: object) -> dict[str, Any]:
    scores = _as_mapping(getattr(sample, "scores", None))
    for name in ("phase13_primary_scorer", "primary_scorer"):
        if name not in scores:
            continue
        payload = _as_mapping(getattr(scores[name], "value", scores[name]))
        return {field: payload[field] for field in _PRIMARY_FIELDS if field in payload}
    return {}


def _profile_identifier(sample: object) -> str | None:
    profile = _as_mapping(
        _store_field(getattr(sample, "store", None), "stakeholder_profile")
    )
    identifier = profile.get("stakeholder_id")
    return identifier if isinstance(identifier, str) and identifier else None


def _run_index(log: EvalLog, sample: object) -> int | None:
    metadata = _sample_metadata(sample)
    args = _task_args(log)
    for source in (metadata, args):
        for key in ("phase14_run_index", "run_index"):
            value = _int_or_none(source.get(key))
            if value is not None:
                return value
    return None


def _limit_parameters(log: EvalLog, sample: object) -> dict[str, int | None]:
    runtime = _runtime_payload(sample)
    metadata = _sample_metadata(sample)
    args = _task_args(log)

    def first_int(*names: str) -> int | None:
        for source in (args, metadata, runtime):
            for name in names:
                value = _int_or_none(source.get(name))
                if value is not None:
                    return value
        return None

    return {
        "max_interview_turns": first_int(
            "max_interview_turns", "phase13_max_interview_turns", "max_turns"
        ),
        "max_candidate_steps_per_turn": first_int(
            "max_candidate_steps_per_turn",
            "phase13_max_candidate_steps_per_turn",
        ),
        "candidate_max_tokens": first_int(
            "candidate_max_tokens", "phase13_candidate_max_tokens"
        ),
    }


def _protocol_summary(log: EvalLog, sample: object) -> dict[str, Any]:
    runtime = _runtime_payload(sample)
    protocol = _as_mapping(runtime.get("protocol_state"))
    metadata = _sample_metadata(sample)
    model_events = [event for event in _events(sample) if _is_model_event(event)]
    stakeholder_events = [
        event for event in model_events if getattr(event, "role", None) == "stakeholder"
    ]
    candidate_events = [
        event for event in model_events if getattr(event, "role", None) != "stakeholder"
    ]
    observations = runtime.get("observations")
    status = protocol.get("status") or metadata.get("interview_status")
    if not isinstance(status, str) or not status:
        status = _text(getattr(log, "status", None)) or "unknown"
    return {
        "status": status,
        "completion_reason": protocol.get("completion_reason"),
        "failure_reason": protocol.get("failure_reason"),
        "candidate_turns": runtime.get(
            "candidate_turns", metadata.get("interview_candidate_turns")
        ),
        "candidate_generation_count": len(candidate_events),
        "candidate_steps": runtime.get(
            "candidate_steps", metadata.get("interview_candidate_steps")
        ),
        "stakeholder_turns": runtime.get(
            "stakeholder_turns", metadata.get("interview_stakeholder_turns")
        ),
        "stakeholder_generation_count": len(stakeholder_events),
        "question_count": runtime.get("question_count"),
        "observation_count": (
            len(observations) if isinstance(observations, Sequence) else None
        ),
    }


def _json_payload(event: object) -> dict[str, Any] | None:
    completion = _event_completion(event)
    if not completion:
        return None
    try:
        value = json.loads(completion)
    except (TypeError, ValueError):
        return None
    return dict(value) if isinstance(value, Mapping) else None


def _as_sequence(value: object) -> list[object]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return list(value)
    return []


def _accepted_stakeholder_entries(
    sample: object,
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Return only ledger entries paired with accepted public observations.

    Initial catalog observations have empty ledger entries and are excluded by
    ``initial_observation_count``.  No raw model completion is used here:
    rejected WHAT/HOW attempts never enter this authoritative accepted set.
    """
    runtime = _runtime_payload(sample)
    ledger = _as_mapping(runtime.get("semantic_ledger"))
    entries = _as_sequence(ledger.get("entries", ledger.get("records")))
    initial_count = _int_or_none(runtime.get("initial_observation_count")) or 0
    observations: dict[str, dict[str, Any]] = {}
    for raw_observation in _as_sequence(runtime.get("observations")):
        observation = _as_mapping(raw_observation)
        identifier = observation.get("id")
        if isinstance(identifier, str) and identifier:
            observations[identifier] = observation

    accepted: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for index, raw_entry in enumerate(entries):
        if index < initial_count:
            continue
        entry = _as_mapping(raw_entry)
        observation_id = entry.get("observation_id")
        if not isinstance(observation_id, str):
            continue
        observation = observations.get(observation_id)
        if observation is None:
            continue
        entry_turn = entry.get(
            "public_message_turn", entry.get("turn", entry.get("message_turn"))
        )
        observation_turn = observation.get(
            "turn",
            observation.get("public_message_turn", observation.get("message_turn")),
        )
        if entry_turn != observation_turn:
            continue
        accepted.append((entry, observation))
    return accepted


def _accepted_response_diagnostics(sample: object) -> dict[str, int]:
    empty_plan = 0
    no_annotations = 0
    insufficient_annotations = 0
    accepted_entries = _accepted_stakeholder_entries(sample)

    for entry, observation in accepted_entries:
        annotations = _as_sequence(entry.get("annotations"))
        message = _text(observation.get("text", observation.get("content")))
        plan_payload = _as_mapping(entry.get("plan"))
        plan_items = _as_sequence(plan_payload.get("items")) if plan_payload else []

        # Phase 13 historically persisted the accepted sidecar, not WHAT. A
        # valid accepted response with no annotations can only have had an
        # empty plan; keep that inference over the historical state shape.
        if not plan_items and not annotations:
            empty_plan += 1
        if message.strip() and not annotations:
            no_annotations += 1

        if plan_payload:
            planned = {
                (item.get("semantic_id"), item.get("mode"))
                for item in plan_items
                if isinstance(item, Mapping)
            }
            covered = {
                (item.get("semantic_id"), item.get("mode"))
                for item in annotations
                if isinstance(item, Mapping)
            }
            if len(covered) < len(planned):
                insufficient_annotations += 1

    return {
        "accepted_response_count": len(accepted_entries),
        "accepted_empty_plan_response_count": empty_plan,
        "accepted_response_with_text_but_no_annotations_count": no_annotations,
        "accepted_response_with_insufficient_annotations_count": insufficient_annotations,
    }


def _event_input_text(event: object) -> str:
    parts: list[str] = []
    for raw_message in _as_sequence(getattr(event, "input", None)):
        if isinstance(raw_message, Mapping):
            value = raw_message.get("text", raw_message.get("content"))
        else:
            value = getattr(raw_message, "text", None)
            if not isinstance(value, str):
                value = getattr(raw_message, "content", None)
        if isinstance(value, str) and value:
            parts.append(value)
    return "\n".join(parts)


def _stakeholder_attempt_phase(event: object) -> str | None:
    """Identify WHAT/HOW from adapter instructions, not natural-language facts."""
    input_text = _event_input_text(event).lower()
    if _REALIZATION_PROMPT_MARKER in input_text:
        return "realization"
    if _PLAN_PROMPT_MARKER in input_text:
        return "plan"
    payload = _json_payload(event)
    if payload is not None:
        if "message" in payload:
            return "realization"
        if "items" in payload:
            return "plan"
    return None


def _is_retry_attempt(event: object) -> bool:
    return _RETRY_PROMPT_MARKER in _event_input_text(event).lower()


def _stakeholder_attempt_diagnostics(sample: object) -> dict[str, int]:
    stakeholder_events = [
        event
        for event in _events(sample)
        if _is_model_event(event) and getattr(event, "role", None) == "stakeholder"
    ]
    groups: list[dict[str, list[object]]] = []
    current: dict[str, list[object]] | None = None
    retry_markers = 0

    for event in stakeholder_events:
        phase = _stakeholder_attempt_phase(event)
        if phase is None:
            # ModelEvent input normally carries the phase marker. For a
            # lightweight fake log, infer the first unlabelled call as WHAT
            # and subsequent calls after a plan as HOW.
            phase = "realization" if current is not None and current["plan"] else "plan"
        if phase == "plan" and current is not None and current["realization"]:
            groups.append(current)
            current = None
        if current is None:
            current = {"plan": [], "realization": []}
        current[phase].append(event)
        try:
            is_retry = _is_retry_attempt(event)
        except (AttributeError, TypeError):
            is_retry = False
        if is_retry:
            retry_markers += 1
    if current is not None:
        groups.append(current)

    accepted_count = len(_accepted_stakeholder_entries(sample))
    plan_attempt_count = sum(len(group["plan"]) for group in groups)
    realization_attempt_count = sum(len(group["realization"]) for group in groups)
    semantic_rejections = 0
    inferred_retries = 0

    for group_index, group in enumerate(groups):
        non_error_plan = [event for event in group["plan"] if not _event_error(event)]
        non_error_realization = [
            event for event in group["realization"] if not _event_error(event)
        ]
        # A later attempt in a phase means the preceding non-provider output
        # was rejected. This also handles terminal retry exhaustion where no
        # accepted ledger entry exists.
        inferred_retries += max(0, len(non_error_plan) - 1)
        inferred_retries += max(0, len(non_error_realization) - 1)
        if group_index < accepted_count:
            semantic_rejections += max(0, len(non_error_plan) - 1)
            semantic_rejections += max(0, len(non_error_realization) - 1)
        elif group["realization"]:
            # Reaching HOW proves that the final WHAT was accepted. HOW has no
            # accepted ledger entry when the overall response failed.
            semantic_rejections += max(0, len(non_error_plan) - 1)
            semantic_rejections += len(non_error_realization)
        else:
            semantic_rejections += len(non_error_plan)

    return {
        "stakeholder_plan_attempt_count": plan_attempt_count,
        "stakeholder_realization_attempt_count": realization_attempt_count,
        "stakeholder_semantic_rejection_count": semantic_rejections,
        "semantic_retry_count": max(retry_markers, inferred_retries),
    }


def _empty_plan_diagnostics(sample: object) -> dict[str, int]:
    """Separate accepted-response counters from raw WHAT/HOW attempts."""
    return {
        **_accepted_response_diagnostics(sample),
        **_stakeholder_attempt_diagnostics(sample),
    }


def _error_records(log: EvalLog, sample: object) -> list[tuple[str, str | None, str]]:
    records: list[tuple[str, str | None, str]] = []
    for event in _events(sample):
        error = _event_error(event)
        if error:
            records.append((type(event).__name__, getattr(event, "role", None), error))
    for source_name, value in (
        ("sample", getattr(sample, "error", None)),
        ("eval", getattr(log, "error", None)),
    ):
        if value:
            records.append((source_name, None, str(value)))
    return records


def _contains_any(text: str, needles: Sequence[str]) -> bool:
    lowered = text.lower()
    return any(needle in lowered for needle in needles)


def _is_stakeholder_semantic_error(text: str) -> bool:
    return _contains_any(
        text,
        (
            "semantic",
            "validation",
            "annotation",
            "response plan",
            "response rejected",
            "invalid stakeholder response",
            "terminology",
            "message must not be blank",
        ),
    )


def _classify_error_text(event_type: str, role: str | None, text: str) -> str | None:
    if event_type == "ToolEvent":
        return "tool/runtime_failure"
    if event_type == "ModelEvent":
        # Semantic output rejection is raised after a successful ModelEvent;
        # an error attached to the event itself is a provider/generation error.
        if role == "stakeholder":
            return "stakeholder_generation_failure"
        return "candidate_generation_failure"
    if _contains_any(text, ("stakeholder",)):
        if _is_stakeholder_semantic_error(text):
            return "stakeholder_semantic_validation_failure"
        return "stakeholder_generation_failure"
    if _contains_any(text, ("candidate", "generation", "generate")):
        return "candidate_generation_failure"
    if _contains_any(text, ("tool", "runtime")):
        return "tool/runtime_failure"
    if _contains_any(text, ("score", "scorer")):
        return "scoring_failure"
    return None


def _authoritative_completion_flag(
    protocol: Mapping[str, Any], primary_evaluation: Mapping[str, Any]
) -> bool | None:
    """Read completion from the score first, then the persisted protocol."""
    scored = primary_evaluation.get("protocol_completed")
    if isinstance(scored, bool):
        return scored
    status = protocol.get("status")
    if status == "completed":
        return True
    if status == "incomplete":
        return False
    return None


def classify_failure(
    log: EvalLog,
    sample: object,
    protocol: Mapping[str, Any],
    primary_evaluation: Mapping[str, Any],
) -> str:
    """Classify the authoritative terminal outcome before incidental errors.

    Tool/model events are diagnostics unless the runtime never reached a
    terminal completion. This prevents a recovered tool error or semantic
    retry from downgrading an otherwise completed interview.
    """
    status = _text(protocol.get("status"))
    scored_completion = primary_evaluation.get("protocol_completed")
    scored_completion_is_false = (
        isinstance(scored_completion, bool) and not scored_completion
    )
    if status == "completed" and not scored_completion_is_false:
        # A missing primary score is still a scoring failure; a valid primary
        # score (including the minimal protocol flag) is authoritative.
        return "completed" if primary_evaluation else "scoring_failure"
    if isinstance(scored_completion, bool) and scored_completion:
        return "completed"

    reason = _text(protocol.get("failure_reason"))
    if reason == "candidate_step_limit_exhausted":
        return "candidate_step_limit"
    if reason in {"max_turns_exhausted", "max_interview_turns_exhausted"}:
        return "interview_turn_limit"

    records = _error_records(log, sample)
    all_errors = " ".join(text for _, _, text in records)
    if not primary_evaluation and _contains_any(all_errors, ("score", "scorer")):
        return "scoring_failure"
    for event_type, role, text in records:
        classification = _classify_error_text(event_type, role, text)
        if classification is not None:
            return classification

    reason_classification = _classify_error_text("reason", None, reason)
    if reason_classification is not None:
        return reason_classification

    authoritative_completion = _authoritative_completion_flag(
        protocol, primary_evaluation
    )
    if status == "incomplete" or (
        isinstance(authoritative_completion, bool) and not authoritative_completion
    ):
        return "incomplete_other"
    if _text(getattr(log, "status", None)) == "success":
        return "completed" if primary_evaluation else "scoring_failure"
    return "incomplete_other"


def _is_false(value: object) -> bool:
    return isinstance(value, bool) and not value


def _quality_tags(primary_evaluation: Mapping[str, Any]) -> list[str]:
    tags: list[str] = []
    if _is_false(primary_evaluation.get("reconstruction_pass")):
        tags.append("reconstruction_failed")
    if _is_false(primary_evaluation.get("evidence_pass")):
        tags.append("evidence_failed")
    if _is_false(primary_evaluation.get("protocol_pass")):
        tags.append("protocol_failed")
    fabricated_nodes = _numeric_or_none(primary_evaluation.get("fabricated_node_count"))
    fabricated_edges = _numeric_or_none(primary_evaluation.get("fabricated_edge_count"))
    if (fabricated_nodes is not None and fabricated_nodes > 0) or (
        fabricated_edges is not None and fabricated_edges > 0
    ):
        tags.append("fabricated_content")
    coverage = _numeric_or_none(primary_evaluation.get("knowledge_coverage"))
    node_recall = _numeric_or_none(primary_evaluation.get("node_recall"))
    if coverage is not None and coverage > 0 and node_recall == 0:
        tags.append("low_knowledge_recovery")
    return tags


def _error_diagnostics(sample: object) -> dict[str, int]:
    """Count incidental model/tool errors separately from terminal outcome."""
    recoverable_tool_errors = 0
    candidate_model_errors = 0
    stakeholder_model_errors = 0
    for event in _events(sample):
        error = _event_error(event)
        if not error:
            continue
        if type(event).__name__ == "ToolEvent":
            recoverable_tool_errors += 1
        elif _is_model_event(event):
            if getattr(event, "role", None) == "stakeholder":
                stakeholder_model_errors += 1
            else:
                candidate_model_errors += 1
    return {
        "recoverable_tool_error_count": recoverable_tool_errors,
        "candidate_model_error_count": candidate_model_errors,
        "stakeholder_model_error_count": stakeholder_model_errors,
    }


def _run_summary(log: EvalLog, sample: object, source_name: str) -> dict[str, Any]:
    runtime = _runtime_payload(sample)
    metadata = _sample_metadata(sample)
    candidate_model, stakeholder_model = _model_names(log, sample)
    primary_evaluation = _score_value(sample)
    protocol = _protocol_summary(log, sample)
    task_args = _task_args(log)
    scenario_id = runtime.get("scenario_id") or metadata.get("scenario_id")
    if not isinstance(scenario_id, str) or not scenario_id:
        scenario_id = task_args.get("scenario_id")
    seed = _store_field(getattr(sample, "store", None), "stakeholder_seed")
    if not isinstance(seed, int) or isinstance(seed, bool):
        seed = None
    eval_id = _text(getattr(log.eval, "eval_id", None)) or None
    run_id = _text(getattr(log.eval, "run_id", None)) or None
    failure_class = classify_failure(log, sample, protocol, primary_evaluation)
    diagnostics = {
        "failure_class": failure_class,
        **_error_diagnostics(sample),
        **_empty_plan_diagnostics(sample),
    }
    tags = _quality_tags(primary_evaluation)
    if failure_class == "completed" and diagnostics["recoverable_tool_error_count"] > 0:
        tags.append("recovered_tool_error")
    if diagnostics["semantic_retry_count"] > 0:
        tags.append("semantic_retry_occurred")
    diagnostics["quality_tags"] = tags
    return {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "run": {
            "scenario_id": scenario_id,
            "candidate_model": candidate_model,
            "stakeholder_model": stakeholder_model,
            "stakeholder_profile_id": _profile_identifier(sample),
            "stakeholder_seed": seed,
            "eval_id": eval_id,
            "run_id": run_id,
            "log_id": eval_id or run_id or source_name,
            "task": (
                _text(getattr(log.eval, "task_registry_name", None))
                or _text(getattr(log.eval, "task", None))
                or None
            ),
            "epoch": _int_or_none(getattr(sample, "epoch", None)),
            "run_index": _run_index(log, sample),
            "limits": _limit_parameters(log, sample),
            "generation_parameters": _generation_parameters(log, sample),
        },
        "protocol": protocol,
        "primary_evaluation": primary_evaluation,
        "usage": _usage_by_role(sample, candidate_model, stakeholder_model),
        "diagnostics": diagnostics,
        "source": {"file_name": source_name},
    }


def extract_run_summaries(
    log: EvalLog, *, source_name: str = "<memory>"
) -> list[dict[str, Any]]:
    """Extract one safe Phase 14 run summary per sample in an EvalLog."""
    samples = getattr(log, "samples", None)
    if not isinstance(samples, Sequence) or isinstance(samples, str) or not samples:
        return []
    safe_source_name = Path(source_name).name
    return [_run_summary(log, sample, safe_source_name) for sample in samples]


def _numeric_values(runs: Sequence[Mapping[str, Any]], key: str) -> list[float]:
    values: list[float] = []
    for run in runs:
        value = _numeric_or_none(run.get(key))
        if value is not None:
            values.append(value if isinstance(value, float) else value * 1.0)
    return values


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _is_true(value: object) -> bool:
    return isinstance(value, bool) and value


def _rate(runs: Sequence[Mapping[str, Any]], key: str) -> float | None:
    values = [run[key] for run in runs if key in run and run[key] is not None]
    return sum(_is_true(value) for value in values) / len(values) if values else None


def _run_completion_flag(run: Mapping[str, Any]) -> bool | None:
    score = _as_mapping(run.get("primary_evaluation"))
    scored = score.get("protocol_completed")
    if isinstance(scored, bool):
        return scored
    protocol = _as_mapping(run.get("protocol"))
    return (
        True
        if protocol.get("status") == "completed"
        else (False if protocol.get("status") == "incomplete" else None)
    )


def _diagnostic_values(runs: Sequence[Mapping[str, Any]], key: str) -> list[float]:
    return _numeric_values(
        [_as_mapping(run.get("diagnostics")) for run in runs],
        key,
    )


def _diagnostic_total(
    runs: Sequence[Mapping[str, Any]], key: str
) -> int | float | None:
    return _sum_usage_field(
        [_as_mapping(run.get("diagnostics")) for run in runs],
        key,
    )


def _accepted_response_rate(
    runs: Sequence[Mapping[str, Any]], numerator_key: str
) -> float | None:
    diagnostics = [_as_mapping(run.get("diagnostics")) for run in runs]
    numerator = _sum_usage_field(diagnostics, numerator_key)
    denominator = _sum_usage_field(diagnostics, "accepted_response_count")
    return numerator / denominator if numerator is not None and denominator else None


def _sum_usage_field(
    values: Sequence[Mapping[str, Any]], field: str
) -> int | float | None:
    present = [
        numeric
        for value in values
        if (numeric := _numeric_or_none(value.get(field))) is not None
    ]
    return sum(present) if present else None


def _aggregate_usage(runs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    aggregate: dict[str, Any] = {}
    for role in ("candidate", "stakeholder", "total"):
        values = [_usage(_as_mapping(run.get("usage")).get(role)) for run in runs]
        costs = [value["total_cost"] for value in values]
        aggregate[role] = {
            "known_run_count": sum(
                any(value is not None for value in usage.values()) for usage in values
            ),
            "input_tokens": _sum_usage_field(values, "input_tokens"),
            "output_tokens": _sum_usage_field(values, "output_tokens"),
            "total_tokens": _sum_usage_field(values, "total_tokens"),
            "mean_input_tokens": _mean(_numeric_values(values, "input_tokens")),
            "mean_output_tokens": _mean(_numeric_values(values, "output_tokens")),
            # Cost is null unless every input run has provider-reported cost.
            "total_cost": (
                sum(costs)
                if costs
                and len(costs) == len(values)
                and all(cost is not None for cost in costs)
                else None
            ),
            "mean_total_tokens": _mean(_numeric_values(values, "total_tokens")),
        }
    return aggregate


def _aggregate_base(runs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    score_runs = [_as_mapping(run.get("primary_evaluation")) for run in runs]
    protocol_runs = [_as_mapping(run.get("protocol")) for run in runs]
    semantic_fields = (
        "activity_correctness",
        "actor_correctness",
        "system_correctness",
        "read_correctness",
        "write_correctness",
        "rationale_correctness",
        "condition_correctness",
        "concept_correctness",
    )
    completion_values = [
        completed
        for run in runs
        if isinstance(completed := _run_completion_flag(run), bool)
    ]
    completion_rate = (
        sum(completion_values) / len(completion_values) if completion_values else None
    )
    return {
        "run_count": len(runs),
        "completion_rate": completion_rate,
        "reconstruction_pass_rate": _rate(score_runs, "reconstruction_pass"),
        "protocol_pass_rate": _rate(score_runs, "protocol_pass"),
        "evidence_pass_rate": _rate(score_runs, "evidence_pass"),
        "mean_node_recall": _mean(_numeric_values(score_runs, "node_recall")),
        "mean_node_precision": _mean(_numeric_values(score_runs, "node_precision")),
        "mean_edge_recall": _mean(_numeric_values(score_runs, "edge_recall")),
        "mean_edge_precision": _mean(_numeric_values(score_runs, "edge_precision")),
        "mean_semantic_correctness": {
            field: _mean(_numeric_values(score_runs, field))
            for field in semantic_fields
        },
        "fabricated_node_total": _sum_usage_field(score_runs, "fabricated_node_count"),
        "fabricated_edge_total": _sum_usage_field(score_runs, "fabricated_edge_count"),
        "average_interview_turns": _mean(
            _numeric_values(protocol_runs, "candidate_turns")
        ),
        "average_candidate_generations": _mean(
            _numeric_values(protocol_runs, "candidate_generation_count")
        ),
        "average_stakeholder_turns": _mean(
            _numeric_values(protocol_runs, "stakeholder_turns")
        ),
        "average_question_count": _mean(
            _numeric_values(protocol_runs, "question_count")
        ),
        "average_observation_count": _mean(
            _numeric_values(protocol_runs, "observation_count")
        ),
        "total_recoverable_tool_error_count": _diagnostic_total(
            runs, "recoverable_tool_error_count"
        ),
        "mean_recoverable_tool_error_count": _mean(
            _diagnostic_values(runs, "recoverable_tool_error_count")
        ),
        "total_stakeholder_semantic_rejection_count": _diagnostic_total(
            runs, "stakeholder_semantic_rejection_count"
        ),
        "mean_stakeholder_semantic_rejection_count": _mean(
            _diagnostic_values(runs, "stakeholder_semantic_rejection_count")
        ),
        "total_semantic_retry_count": _diagnostic_total(runs, "semantic_retry_count"),
        "mean_semantic_retry_count": _mean(
            _diagnostic_values(runs, "semantic_retry_count")
        ),
        "total_accepted_response_count": _diagnostic_total(
            runs, "accepted_response_count"
        ),
        "accepted_empty_plan_rate": _accepted_response_rate(
            runs, "accepted_empty_plan_response_count"
        ),
        "accepted_unannotated_response_rate": _accepted_response_rate(
            runs, "accepted_response_with_text_but_no_annotations_count"
        ),
        "usage": _aggregate_usage(runs),
    }


def _grouped(runs: Sequence[Mapping[str, Any]], field: str) -> dict[str, Any]:
    groups: dict[str, list[Mapping[str, Any]]] = {}
    for run in runs:
        identity = _as_mapping(run.get("run")).get(field)
        key = identity if isinstance(identity, str) and identity else "<unknown>"
        groups.setdefault(key, []).append(run)
    return {key: _aggregate_base(values) for key, values in sorted(groups.items())}


def aggregate_run_summaries(runs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate safe summaries, with scenario/model grouping."""
    run_list = list(runs)
    aggregate = _aggregate_base(run_list)
    aggregate["by_scenario"] = _grouped(run_list, "scenario_id")
    aggregate["by_candidate_model"] = _grouped(run_list, "candidate_model")
    aggregate["by_stakeholder_model"] = _grouped(run_list, "stakeholder_model")
    return aggregate


def summarize_eval_log_object(
    log: EvalLog, *, source_name: str = "<memory>"
) -> dict[str, Any]:
    """Build the JSON object emitted by the Phase 14 summary CLI."""
    runs = extract_run_summaries(log, source_name=source_name)
    return {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "runs": runs,
        "aggregate": aggregate_run_summaries(runs),
    }


def summarize_eval_log(path: str | Path) -> dict[str, Any]:
    """Read one ``.eval`` file and return its deterministic safe summary."""
    log_path = Path(path)
    log = read_eval_log(log_path, resolve_attachments="full")
    return summarize_eval_log_object(log, source_name=log_path.name)


def summarize_eval_logs(paths: Sequence[str | Path]) -> dict[str, Any]:
    """Summarize and aggregate one or more ``.eval`` files."""
    runs: list[dict[str, Any]] = []
    for path in paths:
        runs.extend(summarize_eval_log(path)["runs"])
    return {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "runs": runs,
        "aggregate": aggregate_run_summaries(runs),
    }


def _json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def _yaml_text(value: object) -> str:
    import yaml

    return yaml.safe_dump(
        value,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    )


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 14 .eval diagnostics")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("summarize", "aggregate"):
        command = subparsers.add_parser(
            name, help="extract per-run summaries and aggregate diagnostics"
        )
        command.add_argument("logs", nargs="+", type=Path)
        command.add_argument("--output", "-o", type=Path)
    for name, help_text in (
        ("task-config", "render registered Phase 13 task args for one run"),
        ("run-config", "render one complete Inspect run config for one run"),
    ):
        command = subparsers.add_parser(name, help=help_text)
        command.add_argument("config", type=Path)
        command.add_argument("--run-index", type=int, required=True)
        command.add_argument("--output", "-o", type=Path)
        if name == "run-config":
            command.add_argument("--format", choices=("json", "yaml"))

    args = parser.parse_args(argv)
    try:
        if args.command in {"task-config", "run-config"}:
            config = load_experiment_config(args.config)
            matching = [run for run in config.runs if run.run_index == args.run_index]
            if len(matching) != 1:
                parser.error(
                    "experiment config must contain exactly one "
                    f"run_index={args.run_index}"
                )
            if args.command == "task-config":
                value: object = build_inspect_task_config(matching[0])
            else:
                value = build_inspect_run_config(matching[0])
        else:
            value = summarize_eval_logs(args.logs)
    except ValueError as exc:
        parser.error(str(exc))

    output_format = getattr(args, "format", None)
    if output_format is None and getattr(args, "output", None) is not None:
        if args.output.suffix.lower() in {".yaml", ".yml"}:
            output_format = "yaml"
    text = _yaml_text(value) if output_format == "yaml" else _json_text(value)
    if args.output is None:
        print(text, end="")
    else:
        args.output.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through subprocess
    raise SystemExit(_main())


__all__ = [
    "Phase14ExperimentConfig",
    "Phase14RunConfig",
    "aggregate_run_summaries",
    "build_inspect_run_config",
    "build_inspect_task_config",
    "classify_failure",
    "extract_run_summaries",
    "load_experiment_config",
    "summarize_eval_log",
    "summarize_eval_log_object",
    "summarize_eval_logs",
    "validate_experiment_config",
]
