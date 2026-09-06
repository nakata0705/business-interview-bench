# InterviewState prototype cases

Replay all three cases with the same typed state/tool implementation:

```bash
uv run python -m business_interview.prototype \
  --output-dir examples/interview_state/replays
```

- `normal_existing`: available public observation fixture from seed 9004. The full assistant transcript is not stored, so this is not a reconstructed full conversation.
- `partial_synthetic`: synthetic substitute for unavailable Phase 20/21 partial raw logs.
- `human_synthetic`: synthetic 5–10 minute practice script; human evaluation was not performed.

Each replay writes an `*.state.json`, a readable `*.report.md`,
`tool-schemas.json` generated from the Pydantic inputs, and `manifest.json`.
The case metadata records whether the input is an existing public fixture or
synthetic; generated state does not include simulator-private information.

The human script can be copied to an authorized local directory and replayed
without committing confidential utterances:

```bash
uv run python -m business_interview.prototype \
  --case-dir /tmp/authorized-interview-case \
  --output-dir /tmp/interview-state-replay
```
