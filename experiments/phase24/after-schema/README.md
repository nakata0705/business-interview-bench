# Phase 24: typed `revise_record` provider-schema trial

This directory records one fixed four-turn real-model run after the
`revise_record` schema/runtime alignment. It uses the same public synthetic
conversation and limits as Phase 23; the artifacts contain only public
utterances, typed state, and public assistant text. No provider response,
hidden reasoning, or credential is stored.

## Fixed conversation

1. `申請内容を確認する業務です。`
2. `その確認を担当するのは経理です。`
3. `訂正です。その確認の担当は経理ではなく営業です。`
4. `確認の次に、別の処理として総務が結果を保管します。`

## Model protocol

- Model: `openrouter/openai/gpt-4o-mini`
- `max_tokens=1024`, `max_tool_rounds=4`, `max_tool_calls=8`
- `timeout=60`, no retries, no `--complete`
- `parallel_tool_calls=false`
- `code-sha256.txt` records the `interview_agent.py` hash for this run.

## Observed result

The provider completed without a provider error or timeout, but the semantic
acceptance target was **not met**:

- The initial confirmation step was recorded once.
- The model's actor additions/correction were rejected by the tool path, so
the confirmation step remained `actor=UNSET`; neither accounting nor sales was
recorded.
- The model inferred and recorded a system/data/CRUD resource usage from the
first activity sentence, which was not explicitly stated and violates the
no-inference target.
- The fourth turn correctly added the separate storage step with
`actor=総務` and connected confirmation → storage.

The failure is intentionally preserved in `report-final.md` and
`state-final.json`; deterministic contract tests remain separate from this
real-model result.
