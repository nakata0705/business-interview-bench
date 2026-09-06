# InterviewState prototype cases

Replay all cases with the same typed state/tool implementation:

```bash
uv run python -m business_interview.prototype \
  --output-dir examples/interview_state/replays
```

- `normal_existing`: available public observation fixture from seed 9004. The full assistant transcript is not stored, so this is not a reconstructed full conversation.
- `partial_synthetic`: synthetic substitute for unavailable Phase 20/21 partial raw logs.
- `human_synthetic`: synthetic 5–10 minute practice script; human evaluation was not performed.
- `incremental_synthetic`: synthetic/manual four-turn conformance case for adding and correcting fields on one process step.

Each replay writes an `*.state.json`, a readable `*.report.md`,
`tool-schemas.json` generated from the Pydantic inputs, and `manifest.json`.
`incremental_synthetic` is a synthetic/manual conformance case: its `turns`
register each utterance immediately before the typed calls that cite it, so it
does not pre-register future answers.
The case metadata records whether the input is an existing public fixture or
synthetic; generated state does not include simulator-private information.

The human script can be copied to an authorized local directory and replayed
without committing confidential utterances. The incremental case demonstrates
that `revise_record` targets an existing record plus one typed field, rather than
re-sending the whole process step:

- first addition: `record_id=review`, `field=actor|inputs|outputs`, no `supersedes`
- correction: the same target and field, with the prior active claim in
  `revised_from` and the new claim's `supersedes`

```bash
uv run python -m business_interview.prototype \
  --case-dir /tmp/authorized-interview-case \
  --output-dir /tmp/interview-state-replay
```

## Model-selected short interview

`business_interview_bench.interview_agent` registers each public utterance with
`InterviewHarness`, exposes only harness-issued candidate IDs such as
`candidate:u1:full`, and lets an Inspect model choose the seven typed
operations. The adapter resolves a selected ID to the exact public quote and
range before invoking `InterviewToolExecutor`; no manual operation list is
read by this path. Provider credentials stay in the provider's normal
configuration.

```bash
# Fixed input
uv run python -m business_interview_bench.interview_agent \
  --model openrouter/provider/model \
  --text '担当は営業で、申請書を確認します。' \
  --text '確認結果を記録します。' \
  --complete \
  --checkpoint /tmp/interview-state.checkpoint.json \
  --output /tmp/interview-state.json \
  --report /tmp/interview-state.report.md

# Or interactive Japanese text until /done
uv run python -m business_interview_bench.interview_agent \
  --model openrouter/provider/model --interactive \
  --checkpoint /tmp/interview-state.checkpoint.json
```

The bounded loop executes stateful tool calls serially and limits model/tool
calls, output tokens, timeout, and retries. Automatic claims remain
`provisional`; the adapter rejects unknown evidence candidates and
`stakeholder_confirmed=true`. Empty, truncated, filtered, communication, and
limit failures do not silently complete the interview.

A checkpoint stores the validated `InterviewState`, next utterance counter,
and safe model/config/status metadata. It does not store Inspect conversation
messages, tool-call/receipt history, hidden reasoning, credentials, private
stakeholder state, or unpublished text. Resume it with another public utterance
without replaying prior calls:

```bash
uv run python -m business_interview_bench.interview_agent \
  --model openrouter/provider/model \
  --resume /tmp/interview-state.checkpoint.json \
  --text '訂正です。担当は経理です。' \
  --complete
```

`tests/test_interview_agent.py` exercises the same path with Inspect MockLLM,
including candidate resolution, invalid-candidate/confirmed-claim rejection,
incremental correction, truncation handling, and checkpoint resume. A real
provider run is credential-gated and is not replaced by MockLLM in the
user-facing command.
