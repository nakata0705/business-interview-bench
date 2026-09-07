"""Record the public artifacts for the Phase 25 typed-schema trial."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from inspect_ai.model import ChatMessageAssistant, GenerateConfig, get_model

from business_interview_bench.interview_agent import (
    InterviewAgentError,
    InterviewAgentTurn,
    InterviewStateAgent,
    _invocations_for,
    load_checkpoint,
    render_interview_report,
)

MODEL_NAME = "openrouter/openai/gpt-4o-mini"
UTTERANCES = (
    ("u1", "申請内容を確認する業務です。"),
    ("u2", "その確認を担当するのは経理です。"),
    ("u3", "訂正です。その確認の担当は経理ではなく営業です。"),
    ("u4", "確認の次に、別の処理として総務が結果を保管します。"),
)


def _json_dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _json_load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"cannot read JSON artifact {path}: {exc}") from exc


def _state_identifiers(agent: InterviewStateAgent) -> dict[str, list[str]]:
    state = agent.state
    model = state.business_model
    return {
        "utterance_ids": [item.id for item in state.utterances],
        "claim_ids": [item.id for item in state.claims],
        "process_step_ids": [item.id for item in model.process_steps],
        "flow_ids": [item.id for item in model.flows],
        "actor_ids": [item.id for item in model.actors],
        "system_ids": [item.id for item in model.systems],
        "data_type_ids": [item.id for item in model.data_types],
        "data_operation_ids": [item.id for item in model.data_operations],
    }


def _invocation_records(
    turn: InterviewAgentTurn,
    agent: InterviewStateAgent,
    first_call_order: int,
) -> list[dict[str, Any]]:
    state_identifiers = _state_identifiers(agent)
    records: list[dict[str, Any]] = []
    for offset, invocation in enumerate(turn.invocations):
        receipt = (
            invocation.receipt.model_dump(mode="json")
            if invocation.receipt is not None
            else None
        )
        records.append(
            {
                "utterance_id": turn.utterance_id,
                "call_order": first_call_order + offset,
                "tool_name": invocation.tool_name,
                "call_id": invocation.call_id,
                "arguments": invocation.arguments,
                "success": receipt is not None and receipt["ok"],
                "receipt": receipt,
                "error": invocation.error,
                "state_identifiers_after_turn": state_identifiers,
            }
        )
    return records


def _unrecorded_invocations(
    agent: InterviewStateAgent, records: list[dict[str, Any]]
) -> list[Any]:
    recorded_call_ids = {
        record["call_id"] for record in records if record.get("call_id") is not None
    }
    calls = [
        call
        for message in agent.messages
        if isinstance(message, ChatMessageAssistant)
        for call in message.tool_calls or []
        if call.id not in recorded_call_ids
    ]
    return _invocations_for(calls, agent.messages)


def _tool_schema_document(agent: InterviewStateAgent) -> dict[str, Any]:
    return {
        "schema_version": "business_interview.interview_agent.v3",
        "tools": [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters.model_dump(
                    mode="json", exclude_none=True
                ),
            }
            for tool in agent.tools
        ],
    }


def _write_stage_outputs(
    agent: InterviewStateAgent,
    output_dir: Path,
    *,
    state_name: str,
    report_name: str,
) -> None:
    _json_dump(output_dir / state_name, agent.state.model_dump(mode="json"))
    (output_dir / report_name).write_text(
        render_interview_report(
            agent.state,
            metadata=agent.metadata,
            public_messages=agent.public_messages,
        )
        + "\n",
        encoding="utf-8",
    )


def _model(model_name: str) -> Any:
    return get_model(
        model_name,
        config=GenerateConfig(
            max_tokens=1024,
            timeout=60,
            max_retries=0,
            parallel_tool_calls=False,
        ),
        memoize=False,
    )


async def _run_first(model_name: str, output_dir: Path) -> None:
    model = _model(model_name)
    async with model:
        agent = InterviewStateAgent(
            model,
            max_tool_rounds=4,
            max_tool_calls=8,
            max_tokens=1024,
            request_timeout=60,
        )
        turn = await agent.process_utterance(UTTERANCES[0][1], utterance_id="u1")
        agent.save_checkpoint(output_dir / "checkpoint-u1.json")
        _json_dump(
            output_dir / "invocations-u1.json",
            _invocation_records(turn, agent, first_call_order=1),
        )
        _json_dump(output_dir / "tool-schema.json", _tool_schema_document(agent))
        _write_stage_outputs(
            agent,
            output_dir,
            state_name="state-u1.json",
            report_name="report-u1.md",
        )


async def _run_resume(model_name: str, output_dir: Path) -> None:
    checkpoint_path = output_dir / "checkpoint-u1.json"
    try:
        checkpoint = load_checkpoint(checkpoint_path)
    except (OSError, ValueError) as exc:
        raise SystemExit(f"cannot load checkpoint {checkpoint_path}: {exc}") from exc
    model = _model(model_name)
    async with model:
        agent = InterviewStateAgent.from_checkpoint(
            model,
            checkpoint,
            max_tool_rounds=4,
            max_tool_calls=8,
            max_tokens=1024,
            request_timeout=60,
        )
        records = _json_load(output_dir / "invocations-u1.json")
        call_order = len(records) + 1
        for utterance_id, text in UTTERANCES[1:]:
            try:
                turn = await agent.process_utterance(text, utterance_id=utterance_id)
            except InterviewAgentError as exc:
                failed_invocations = _unrecorded_invocations(agent, records)
                failure_turn = InterviewAgentTurn(
                    utterance_id=utterance_id,
                    assistant_text="",
                    invocations=tuple(failed_invocations),
                )
                records.extend(_invocation_records(failure_turn, agent, call_order))
                _json_dump(output_dir / "invocations.json", records)
                _json_dump(
                    output_dir / f"failure-{utterance_id}.json",
                    {
                        "utterance_id": utterance_id,
                        "kind": exc.kind,
                        "error": str(exc),
                        "state_identifiers": _state_identifiers(agent),
                    },
                )
                _write_stage_outputs(
                    agent,
                    output_dir,
                    state_name=f"state-failure-{utterance_id}.json",
                    report_name=f"report-failure-{utterance_id}.md",
                )
                raise
            new_records = _invocation_records(turn, agent, call_order)
            records.extend(new_records)
            call_order += len(new_records)
        agent.mark_user_stopped()
        agent.save_checkpoint(output_dir / "checkpoint-final.json")
        _json_dump(output_dir / "invocations.json", records)
        _write_stage_outputs(
            agent,
            output_dir,
            state_name="state-final.json",
            report_name="report-final.md",
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("first", "resume"))
    parser.add_argument("--model", default=MODEL_NAME)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "first":
        asyncio.run(_run_first(args.model, args.output_dir))
    else:
        asyncio.run(_run_resume(args.model, args.output_dir))


if __name__ == "__main__":
    main()
