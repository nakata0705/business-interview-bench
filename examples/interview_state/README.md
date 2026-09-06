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
