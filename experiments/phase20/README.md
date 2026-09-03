# Phase 20: stakeholder WHAT semantic-failure diagnosis and hardening

Phase 20 is the follow-up to the Phase 19 Inspect-native stakeholder
WHAT/HOW contract. It diagnoses the observed WHAT failures, makes the smallest
safe prompt/retry/schema changes, and records a fresh real-provider check and
calibration without committing raw `.eval` logs.

## Phase 19 diagnosis

The two persisted Phase 19 quotation logs were reclassified with the typed
core validator. Across seven WHAT attempts:

| category | count |
| --- | ---: |
| canonical mode mismatch | 6 |
| unresolvable semantic address | 0 |
| realization semantic mismatch | 0 |
| structural output rejection | 0 |
| output exhaustion | 0 |
| provider error | 0 |
| valid WHAT attempts | 1 |

The failures were therefore mode-selection failures, not evidence of provider
instability or a malformed provider schema. The unavailable Phase 19 lab
attempt remains unavailable and was not used to manufacture a count.

## Changes

- `ResponseValidationError` carries a typed failure code for unresolvable
  addresses, canonical mode mismatches, and realization mismatches.
- WHAT/HOW diagnostics retain separate structural, semantic, address, mode, and
  realization counters. Retry guidance names the failing category without
  echoing private completion text.
- Every selectable private semantic address now renders its canonical
  `required_mode` beside the address. The WHAT instruction says to copy that
  mode exactly and asks for relevant non-empty plans when knowledge supports
  the question; empty plans remain valid for genuinely unknown questions.
- The adapter uses Inspect's official `json_schema()` helper for both schemas.
  The schemas remain non-strict, object-root, closed, and reference-free after
  conversion to Inspect's `JSONSchema` model.
- The validated WHAT plan is persisted in each accepted semantic-ledger entry.
  Phase 14's accepted-response metrics now count non-empty plans and annotated
  HOW responses from that authoritative ledger, never by inferring from public
  prose.

The core 41-field evaluator and candidate tool surface are unchanged.

## Deterministic validation

The deterministic MockLLM tests cover typed failure categories, safe retry
messages, canonical-mode prompt rendering, official-schema equivalence,
ledger plan persistence, accepted non-empty/annotated counts, and protocol
exhaustion/error classification.

## Real-provider preflight

`preflight.json` records a direct adapter preflight using the exact target
model:

- scenario: `lab_sample_flow`
- question scope: the activity performed when a sample first arrives
- structured output: `inspect_response_schema`
- provider retries: `0`
- accepted public response: `1`
- accepted non-empty WHAT: `1`
- accepted annotated HOW: `1`
- WHAT/HOW semantic, structural, output-exhaustion, and provider errors: `0`

The preflight also ingested the accepted response into the live semantic
ledger. It is a targeted semantic check, not a substitute for the full
three-run calibration.

## Fresh calibration

`calibration.json` fixes one epoch for each of the three historical scenarios,
with the exact model
`openrouter/deepseek/deepseek-v4-flash-0731`. Candidate generation is
`temperature: 0.0` with the runtime `candidate_max_tokens: 1024`; stakeholder
generation is `temperature: 0.0` and `reasoning_effort: low`, with no
stakeholder token bound. Limits are `max_interview_turns=8` and
`max_candidate_steps_per_turn=8`. Each run was launched once with provider
retries disabled:

```bash
inspect eval --run-config /tmp/phase20-real-calibration/configs/phase20-run-0.yaml \
  --max-retries 0 --log-dir /tmp/phase20-real-calibration/logs/run-0
inspect eval --run-config /tmp/phase20-real-calibration/configs/phase20-run-1.yaml \
  --max-retries 0 --log-dir /tmp/phase20-real-calibration/logs/run-1
inspect eval --run-config /tmp/phase20-real-calibration/configs/phase20-run-2.yaml \
  --max-retries 0 --log-dir /tmp/phase20-real-calibration/logs/run-2
```

The observed results are summarized safely in
`real-calibration-summary.json`:

| run | scenario | terminal result | accepted | non-empty WHAT | annotated HOW | WHAT/HOW semantic retries | provider errors |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: |
| 0 | `lab_sample_flow` | candidate did not ask a question | 2 | 2 | 2 | 0 | 0 |
| 1 | `quotation_workflow_1` | candidate step limit | 1 | 1 | 1 | 0 | 0 |
| 2 | `quotation_workflow_1_ja` | unavailable: timeout before sample persistence | — | — | — | — | — |

The two observed samples each contain the unchanged 41 primary evaluation
fields. The Japanese run is explicitly unavailable rather than a zero score;
no earlier log was substituted. Raw provider logs and rendered configs remain
under `/tmp/phase20-real-calibration/` only.

## Safe artifacts

- `calibration.json`: reproducible three-run manifest.
- `preflight.json`: redacted targeted real-provider acceptance evidence.
- `real-calibration-summary.json`: redacted per-run/aggregate results and
  typed diagnostics.

No artifact contains Truth, exact stakeholder knowledge, private local
semantic IDs, raw model completions, or reasoning content.
