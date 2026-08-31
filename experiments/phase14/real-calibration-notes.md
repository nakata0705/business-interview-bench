# Phase 14 initial real-provider calibration

- Target HEAD: `a8c190690a6e6b072d3dc23da6613ea644232156`
- Provider/model: `openrouter/openai/gpt-4o-mini` for both candidate and stakeholder
- Credential/provider availability: `OPENROUTER_API_KEY` was present, the
  Inspect OpenRouter adapter was available after its optional `openai`
  dependency was installed in the local environment, and the selected model
  was listed by the provider. No credential value was saved.
- Epochs: 1 per run
- Calibration policy: first attempt only; no score-based retries and no transient retry was used
- Safe summary: `experiments/phase14/real-calibration-summary.json`

## Execution result

All three Inspect commands exited normally, but each produced an error-status
`.eval` log during the first candidate generation. No stakeholder generation was
reached, and no primary scorer output was produced. The three errors were the
same HTTP 400 provider response:

> Invalid schema for function `update_node`: in context
> `('properties', 'updates', 'additionalProperties')`, schema must have a
> `type` key (`invalid_function_parameters`).

This is a request/tool-schema compatibility failure, not a transient provider
failure. No retry was attempted.

| run | scenario | profile | seed | log outcome | failure class | candidate generations | stakeholder generations | primary score |
| ---: | --- | --- | ---: | --- | --- | ---: | ---: | --- |
| 0 | `lab_sample_flow` | `phase14-lab-technician` | 1401 | error before interview | `candidate_generation_failure` | 1 | 0 | unavailable |
| 1 | `quotation_workflow_1` | `phase14-sales-owner` | 1402 | error before interview | `candidate_generation_failure` | 1 | 0 | unavailable |
| 2 | `quotation_workflow_1_ja` | `phase14-sales-owner-ja` | 1403 | error before interview | `candidate_generation_failure` | 1 | 0 | unavailable |

The persisted protocol state for every run was active with one candidate step,
zero questions, one initial observation, and zero stakeholder turns. There were
no recoverable tool errors, semantic retries, semantic rejections, or accepted
responses. Candidate/stakeholder/total token usage and provider-reported cost
were not recorded, so they are left `null` rather than estimated.

Because no run reached scoring, all 41 primary-evaluation fields are unavailable
(`primary_evaluation` is empty in the safe summary):
`protocol_completed`, `reconstruction_pass`, `structural_pass`, `evidence_pass`,
`protocol_pass`, node/edge recall and precision, activity/actor/system/read/write/
rationale/condition/concept correctness and concept recall/precision, fabricated
node/edge counts, and `knowledge_coverage`.

## Failure attribution

- **A Candidate interview strategy:** not reached; no evidence.
- **B Candidate graph/tool usage:** the candidate request was rejected while
  serializing the graph tool surface, before the candidate could use a tool.
- **C Stakeholder WHAT selection:** not reached.
- **D Stakeholder HOW realization:** not reached.
- **E Semantic validation/retry friction:** not reached; all retry/rejection
  counters are zero.
- **F Runtime limit:** not reached; no configured limit was exhausted.
- **G Evaluator/alignment:** not reached; no primary score was emitted.
- **H Scenario/profile difficulty:** no evidence; the identical failure occurred
  across all three scenarios before scenario-specific interview behavior.

## Phase 15 priority

**Primary target:** make the Inspect candidate tool schemas accepted by the
selected OpenAI-compatible provider, starting with the `update_node` arbitrary
`updates` object (and audit the analogous graph update tool schemas). This is
an integration/runtime correctness issue: it blocks every scenario before
measurement, so it has cross-scenario impact and prevents any valid benchmark
score. This calibration did not modify it or tune prompts/evaluation.

Raw logs remain outside the repository under `/tmp/phase14-real-calibration/`:

- `/tmp/phase14-real-calibration/logs/run-0/2026-08-31T17-04-20-00-00_phase13-interview_3ufyAgbhaYeq8rSZCnx69V.eval`
- `/tmp/phase14-real-calibration/logs/run-1/2026-08-31T17-04-31-00-00_phase13-interview_HbFysm7V2oGnv2VwPEA6i6.eval`
- `/tmp/phase14-real-calibration/logs/run-2/2026-08-31T17-04-41-00-00_phase13-interview_PS7TjeGLqCx2ydejz4nFcH.eval`
