# Phase 16 reasoning-token diagnostics

Phase 16 adds safe diagnostics to the existing Phase 14 summary path. It does
not change benchmark prompts, evaluators, scenarios, stakeholder profiles,
reasoning settings, retry policy, graph mutation semantics, or the 41-field
primary evaluator. Core `business_interview` remains independent of
`inspect_ai` and `tau2`.

## Calibration protocol

Exactly one unchanged real-provider run was executed:

- task: `business_interview_bench/phase13_interview`
- scenario: `lab_sample_flow`
- candidate and stakeholder: `openrouter/deepseek/deepseek-v4-flash-0731`
- profile: `phase14-lab-technician`
- stakeholder seed: `1401`
- epoch: `1`
- limits: `max_interview_turns=8`, `max_candidate_steps_per_turn=8`,
  `candidate_max_tokens=1024`
- generation: temperature `0.0`
- provider/API retry flag: `--max-retries 0`, unchanged from Phase 15

The run was launched from run index `0` of the Phase 15 calibration manifest.
The temporary run config and raw `.eval` log remain outside the repository
under `/tmp/phase16-real-calibration/`. Only the safe result is committed as
`real-calibration-summary.json`.

## Diagnostics contract

`ModelUsage.reasoning_tokens` is retained when the provider reports it.
`non_reasoning_output_tokens` is calculated as
`output_tokens - reasoning_tokens` only when both values are present and
non-negative with reasoning no greater than output. Otherwise it is `null` and
`diagnostics.usage_warnings` records a stable warning code. `reasoning_share` is
reported as reasoning divided by output when defined. The same fields are
present for candidate, stakeholder, total, and aggregate usage, with role
separation preserved for a shared model.

`generation_usage` contains one safe record per candidate/stakeholder
`ModelEvent`: role, WHAT/HOW phase (candidate phase is `unknown`), response and
attempt indexes, retry status, accepted status for stakeholder attempts, token
usage, and visible completion character count. Standard Inspect does not expose
visible completion token count separately from reasoning, so
`visible_completion_estimated_tokens` remains `null`; raw completions are never
stored.

A stakeholder WHAT attempt is accepted when it is the final attempt that
reaches HOW. A HOW attempt is accepted only when the authoritative accepted
ledger contains its response. Every other WHAT/HOW generation is rejected for
the attempt split. Retry status is explicit when the adapter marker is logged,
and otherwise inferred from the attempt index in the phase. These diagnostics
are descriptive only.

## Observed result

The run ended with Inspect log status `error` while the runtime protocol state
remained `active`. The safe terminal class is
`stakeholder_semantic_validation_failure`; there were no recoverable tool
errors or model-event errors. The stakeholder response adapter raised its
existing structured-response error after three semantic retries, and no
primary score was produced.

| metric | value |
| --- | ---: |
| candidate generations | 1 |
| stakeholder generations | 5 (2 WHAT, 3 HOW) |
| accepted public responses | 0 |
| accepted phase attempts | 1 (WHAT only) |
| rejected phase attempts | 4 |
| semantic retries | 3 |
| primary score fields | 0 |

Provider usage (cost was not reported):

| role | input | output | reasoning | non-reasoning output | total | reasoning share |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| candidate | 2,311 | 118 | 97 | 21 | 2,429 | 82.20% |
| stakeholder | 13,506 | 99,847 | 96,852 | 2,995 | 113,353 | 97.00% |
| total | 15,817 | 99,965 | 96,949 | 3,016 | 115,782 | 96.98% |

Rejected phase attempts consumed 82,594 reasoning tokens, 85,297 output
tokens, and 96,471 total tokens. Relative to all stakeholder usage, these are
85.28%, 85.43%, and 85.11%, respectively. The three retry generations alone
consumed 26,990 reasoning tokens, 29,938 output tokens, and 38,410 total
tokens (27.87%, 29.98%, and 33.89% of stakeholder usage). The accepted-phase
WHAT attempt consumed 14,258 reasoning tokens and 16,882 total tokens; it did
not become an accepted public response because HOW never passed validation.

Visible completion character counts for the five stakeholder generations were
`0`, `216`, `1,862`, `3,600`, and `3,601` (minimum `0`, median `1,862`, maximum
`3,601`). No visible-token estimate was asserted. The zero-character generation
also reported 68,691 output/reasoning tokens, which is consistent with a
reasoning-heavy invalid structured-response path but is not by itself a causal
claim.

The next hardening priority remains the stakeholder structured-response
runtime path and its parse/semantic-validation observability. No prompt,
scenario, evaluator, threshold, retry, or reasoning tuning was performed for
this diagnostic.

No credentials, private stakeholder knowledge, full prompts, transcripts, or
raw `.eval` content are stored in the Phase 16 artifacts. Phase 14 and Phase 15
artifacts remain unchanged.
