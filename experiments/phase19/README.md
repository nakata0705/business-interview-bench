# Phase 19: Inspect-native stakeholder WHAT/HOW structured output

Phase 19 restores native Inspect structured-output handling for the stakeholder
WHAT/HOW contract. It is an implementation and calibration phase, not a
replacement of the historical Phase 18 measurement.

Phase 18 remains unchanged at commit
`bf6c6fe1171f3e3e448d5a9290612b6c63ebdaaa`. Its fixed stakeholder policy was
`temperature: 0.0`, `reasoning_effort: low`, no stakeholder `max_tokens`, and
`--max-retries 0`.

## Implementation contract

The stakeholder adapter now passes an Inspect `ResponseSchema` for both
`SemanticResponsePlan` (WHAT) and `StakeholderResponse` (HOW). The schemas are
provider-facing JSON Schema objects with `strict: false`; Pydantic definitions
are inlined so the OpenRouter request has an object root, closed properties,
and no unresolved `$defs`/`$ref` references. Deterministic Pydantic parsing and
the existing strict semantic validators remain authoritative.

Only harmless JSON wrappers (fences and surrounding prose) are extracted. The
adapter does not repair malformed JSON, invent fields, or relax semantic
checks. Every bounded stakeholder attempt is classified as structural,
semantic, output-exhaustion, or provider failure. Exhaustion is terminal and
marks the interview incomplete while preserving an unanswered candidate
question; no stakeholder response is fabricated.

The safe summary records per-generation phase, attempt, retry, acceptance,
structured-output mode, token usage, and visible-character counts. It never
stores prompts, completions, reasoning text, private knowledge, credentials,
or raw `.eval` content.

## Fixed calibration protocol

`calibration.json` contains the same three requested scenarios and one manifest
entry per scenario:

| run | scenario | profile | seed |
| ---: | --- | --- | ---: |
| 0 | `lab_sample_flow` | `phase14-lab-technician` | 1401 |
| 1 | `quotation_workflow_1` | `phase14-sales-owner` | 1402 |
| 2 | `quotation_workflow_1_ja` | `phase14-sales-owner-ja` | 1403 |

Both roles use
`openrouter/deepseek/deepseek-v4-flash-0731`. Candidate settings are
`temperature: 0.0` and runtime `candidate_max_tokens: 1024`. Stakeholder
settings are `temperature: 0.0` and `reasoning_effort: low`; no stakeholder
`max_tokens` is configured. Limits are `max_interview_turns=8`,
`max_candidate_steps_per_turn=8`, and `epoch=1`. Inspect provider retries were
disabled with `--max-retries 0`; the adapter's own semantic retry bound remains
three attempts.

The requested lab run did not persist an Inspect sample before the provider
wall-clock timeout. It is reported as unavailable, not as a zero score. The
English and Japanese quotation runs each produced one persisted sample and are
the two observed runs in `real-calibration-summary.json`. The timed-out lab
attempt is not silently substituted with an earlier or differently prompted
run.

## Native-schema preflight

Direct OpenRouter preflight succeeded for both schemas:

| schema | stop | input | output | reasoning | total |
| --- | --- | ---: | ---: | ---: | ---: |
| `semantic_response_plan` | `stop` | 204 | 6 | 0 | 210 |
| `stakeholder_response` | `stop` | 18 | 14 | 0 | 32 |

Provider-reported cost was unavailable for both probes. These probes validate
request compatibility only; they are not benchmark samples.

## Observed calibration results

The table below covers only the two persisted samples. “Attempts” includes the
initial attempt and “accepted” is the count accepted by the corresponding
WHAT/HOW parser and validator.

| run | candidate turns / generations / steps / questions | stakeholder turns / generations | WHAT attempts (accepted) | HOW attempts (accepted) | semantic rejects / retries | accepted public responses |
| ---: | --- | --- | --- | --- | ---: | ---: |
| 1 quotation EN | 2 / 3 / 1 / 2 | 1 / 5 | 4 (1) | 1 (1) | 3 / 2 | 1 |
| 2 quotation JA | 1 / 2 / 2 / 1 | 0 / 3 | 3 (0) | 0 (0) | 3 / 2 | 0 |
| **observed total** | **3 / 5 / 3 / 3** | **1 / 8** | **7 (1)** | **1 (1)** | **6 / 4** | **1** |

The English run accepted one complete stakeholder response, then exhausted
WHAT semantic retries on a later candidate question and ended with
`stakeholder_what_semantic_exhausted`. The Japanese run exhausted WHAT
semantic retries on its first question and ended with the same terminal reason.
No persisted attempt was structurally rejected, output-exhausted, or classified
as a provider error. The unavailable lab run has no attempt, usage, or quality
metrics.

Observed native structured-output mode was `inspect_response_schema` for every
stakeholder generation. The safe aggregate reports six semantic validation
rejections, four adapter retries, zero structural rejections, zero output
exhaustions, and zero persisted provider errors.

## Usage diagnostics

All values are provider-reported except `non_reasoning_output_tokens`, which is
the derived value `output_tokens - reasoning_tokens`. No cost is estimated.

| run | role | input | output | reasoning | non-reasoning output | total | reasoning share |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | candidate | 7,217 | 316 | 193 | 123 | 7,533 | 61.08% |
| 1 | stakeholder | 16,068 | 3,500 | 2,865 | 635 | 19,568 | 81.86% |
| 1 | total | 23,285 | 3,816 | 3,058 | 758 | 27,101 | 80.14% |
| 2 | candidate | 4,875 | 303 | 198 | 105 | 5,178 | 65.35% |
| 2 | stakeholder | 10,231 | 5,521 | 4,998 | 523 | 15,752 | 90.53% |
| 2 | total | 15,106 | 5,824 | 5,196 | 628 | 20,930 | 89.22% |
| **all observed** | **candidate** | **12,092** | **619** | **391** | **228** | **12,711** | **63.17%** |
| **all observed** | **stakeholder** | **26,299** | **9,021** | **7,863** | **1,158** | **35,320** | **87.16%** |
| **all observed** | **total** | **38,391** | **9,640** | **8,254** | **1,386** | **48,031** | **85.62%** |

## Evaluation scope and attribution

Neither observed run reached a completed interview. Inspect nevertheless
persisted the unchanged 41-field `PrimaryEvaluation` for each incomplete
sample. Those records report `protocol_completed=false`,
`reconstruction_pass=false`, and `quality_pass=false` for the partial
transcripts; they are retained as evaluator output, not replaced with inferred
zeros. They are not comparable to a completed-interview quality measurement.
The unavailable lab run has no evaluator record, and no score is inferred for
it.

The observed blocker is still stakeholder WHAT semantic validation after a
response has passed the provider's JSON structure check. The new diagnostics
separate that blocker from provider and output-exhaustion failures and make the
runtime terminal state explicit. A larger controlled calibration is required
before drawing a quality conclusion from these two samples.

## Safe artifacts and validation

- `calibration.json` — the exact three-scenario Phase 19 manifest.
- `real-calibration-summary.json` — safe summaries for two persisted samples,
  preflight evidence, aggregate diagnostics, and the explicit unavailable lab
  record.
- this `README.md` — protocol, implementation contract, calibration results,
  usage, and scoring scope.

Validation used the targeted adapter/Inspect/summary tests, Ruff formatting and
lint checks, Pyright, and the full test suite. Historical Phase 14–18
measurement artifacts were not regenerated or modified.
