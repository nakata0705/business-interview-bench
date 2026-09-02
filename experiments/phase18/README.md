# Phase 18: full calibration with stakeholder reasoning `low`

Phase 18 measures the three historical calibration scenarios with the
stakeholder `reasoning_effort` fixed to `low`. It is a measurement phase, not a
policy comparison or a tuning phase.

The target baseline is commit `e34213a449bf6bdc8ba43896308bd60ab7af915b`.
Historical Phase 14--17 artifacts are unchanged.

## Fixed protocol

`calibration.json` is a dedicated Phase 18 manifest with exactly one run per
scenario:

| run | scenario | profile | seed |
| ---: | --- | --- | ---: |
| 0 | `lab_sample_flow` | `phase14-lab-technician` | 1401 |
| 1 | `quotation_workflow_1` | `phase14-sales-owner` | 1402 |
| 2 | `quotation_workflow_1_ja` | `phase14-sales-owner-ja` | 1403 |

Both roles use the exact model
`openrouter/deepseek/deepseek-v4-flash-0731`. Candidate settings remain the
Phase 15/17 baseline (`temperature: 0.0`, runtime `candidate_max_tokens: 1024`).
The stakeholder uses `temperature: 0.0` and `reasoning_effort: low`; no
stakeholder `max_tokens` is configured. Limits are `max_interview_turns=8`,
`max_candidate_steps_per_turn=8`, and `epoch=1`.

Each rendered config passed `RunConfigInput` validation and was checked to
contain the stakeholder settings above, no candidate reasoning policy, and no
stakeholder token bound. The authoritative commands were run once per
scenario, with `--max-retries 0`:

```bash
inspect eval --run-config /tmp/phase18-real-calibration/phase18-run-0.yaml \
  --max-retries 0
inspect eval --run-config /tmp/phase18-real-calibration/phase18-run-1.yaml \
  --max-retries 0
inspect eval --run-config /tmp/phase18-real-calibration/phase18-run-2.yaml \
  --max-retries 0
```

Raw `.eval` logs and rendered temporary configs remain outside Git under
`/tmp/phase18-real-calibration/`. No run was repeated: there was no transient
provider/infrastructure failure.

## Terminal and structured-response results

The Inspect log status was `error` for all three runs. The persisted runtime
status was still `active` because the existing stakeholder exception propagated
before the runtime could mark a terminal state. The safe terminal classification
is `stakeholder_semantic_validation_failure` in every run, with no persisted
runtime `failure_reason` (`null`). The underlying safe error shape was the
existing `StakeholderResponseError` after three realization attempts with
`invalid StakeholderResponse JSON` as its final reason.

| run | candidate turns / generations / steps / questions | stakeholder turns / generations | WHAT attempts (accepted) | HOW attempts (accepted) | semantic rejects / retries | accepted public responses |
| ---: | --- | --- | --- | --- | ---: | ---: |
| 0 lab | 1 / 2 / 2 / 1 | 0 / 4 | 1 (1) | 3 (0) | 3 / 2 | 0 |
| 1 quotation EN | 1 / 2 / 2 / 1 | 0 / 6 | 3 (1) | 3 (0) | 5 / 4 | 0 |
| 2 quotation JA | 1 / 1 / 1 / 1 | 0 / 4 | 1 (1) | 3 (0) | 3 / 2 | 0 |
| **total** | **3 / 5 / 5 / 3** | **0 / 14** | **5 (3)** | **9 (0)** | **11 / 8** | **0** |

Therefore:

- WHAT became valid in all three scenarios (`3/3`). The English quotation
  run needed two WHAT retries; lab and Japanese quotation passed WHAT on the
  first attempt.
- HOW became valid in none of the scenarios (`0/3`). No HOW path produced an
  accepted public response, and all three exhausted the existing three-attempt
  realization bound.
- The run-level safe per-generation records, including phase, attempt index,
  retry, accepted flag, requested effort, token usage, and visible character
  count, are in `real-calibration-summary.json` under
  `runs[].generation_usage.stakeholder`.

### Per-run safe failure evidence

- **Lab:** the candidate asked one question after two generations and used only
  read-only graph/observation tools. WHAT passed. The first HOW response parsed
  as JSON but omitted planned semantic items; the two retries failed strict
  response parsing.
- **Quotation EN:** the candidate asked one question after two read-only
  generations. The first two WHAT attempts failed strict parsing, including one
  provider generation with a `max_tokens` stop and no visible completion; the
  third WHAT passed. The first HOW response omitted planned semantic items and
  the two retries failed strict parsing.
- **Quotation JA:** the candidate asked one question directly without a graph
  tool call. WHAT passed. The first HOW response had a non-exact annotation
  quote span; both retries had no visible completion and failed strict parsing.

These descriptions intentionally contain no completion text, private knowledge,
local semantic IDs, or transcript material.

## Usage and reasoning diagnostics

All values below are provider-reported usage. `non_reasoning_output_tokens` is
the safe derived field `output_tokens - reasoning_tokens`; provider-reported cost
was unavailable (`null`) for every role and run, and no cost is estimated.
Reasoning-share is reasoning divided by output.

| run | role | input | output | reasoning | non-reasoning output | total | reasoning share | cost |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 0 | candidate | 4,691 | 139 | 72 | 67 | 4,830 | 51.80% | unavailable |
| 0 | stakeholder | 11,631 | 22,725 | 18,185 | 4,540 | 34,356 | 80.02% | unavailable |
| 0 | total | 16,322 | 22,864 | 18,257 | 4,607 | 39,186 | 79.85% | unavailable |
| 1 | candidate | 4,695 | 140 | 77 | 63 | 4,835 | 55.00% | unavailable |
| 1 | stakeholder | 14,860 | 144,833 | 126,593 | 18,240 | 166,349 | 87.41% | unavailable |
| 1 | total | 19,555 | 144,973 | 126,670 | 18,303 | 171,184 | 87.37% | unavailable |
| 2 | candidate | 2,334 | 172 | 144 | 28 | 2,506 | 83.72% | unavailable |
| 2 | stakeholder | 5,072 | 7,530 | 5,075 | 2,455 | 24,378 | 67.40% | unavailable |
| 2 | total | 7,406 | 7,702 | 5,219 | 2,483 | 26,884 | 67.76% | unavailable |
| **all** | **candidate** | **11,720** | **451** | **293** | **158** | **12,171** | **64.97%** | **unavailable** |
| **all** | **stakeholder** | **31,563** | **175,088** | **149,853** | **25,235** | **225,083** | **85.59%** | **unavailable** |
| **all** | **total** | **43,283** | **175,539** | **150,146** | **25,393** | **237,254** | **85.53%** | **unavailable** |

There were no usage-accounting warnings. Low did **not** eliminate an extreme
individual reasoning generation: the English quotation WHAT retry reported
`115,037` reasoning tokens, `131,072` output tokens, zero visible completion
characters, and a `max_tokens` stop. The next-highest stakeholder generation
was `7,665` reasoning tokens. This is a descriptive outlier from the observed
14 stakeholder generations, not a newly introduced benchmark threshold. It is
also larger than the entire Phase 16 lab reasoning total (`96,852`), so the
Phase 16-style spike is not ruled out by the low request.

## Primary evaluation and benchmark quality

No run reached `PrimaryEvaluation`: all three failed in stakeholder realization
before a public response could be appended. Consequently
`runs[].primary_evaluation` is `{}` for every run in the safe summary. Node/edge
structure, graph reconstruction, start/end, all activity/actor/system/read/write/
rationale/condition/concept fields, evidence/provenance coverage, authentic and
orphan observations, invalid evidence/reference counts, fabricated counts, and
`knowledge_coverage` are **not measured** in Phase 18; no zero score is inferred.

The safe location for this result is
`real-calibration-summary.json` (`phase18.primary_evaluation` and each
`runs[].primary_evaluation`). The unchanged 41-field contract remains covered
by the seed9004 41/41 regression and the existing Phase 13--17 tests.

The candidate did not reach graph mutation in any run. Lab and English used
`get_agent_graph` and `get_observations` before asking a question; Japanese used
no graph tool. The observed graph remained empty in all three logs. There were
zero recoverable tool errors, so neither the Phase 15 unknown-concept-reference
pattern nor the invalid-evidence-quote-span pattern occurred.

## A--H qualitative attribution

| category | Phase 18 observation |
| --- | --- |
| **A. Candidate interview strategy** | No `candidate_did_not_ask_question` failure. All three candidates asked one question before the stakeholder block; later strategy was not observable. |
| **B. Candidate graph/tool usage** | Lab and English only read the empty graph/observations; Japanese made no graph tool call. No mutation or meaningful reconstruction was reached. |
| **C. Stakeholder WHAT** | Valid eventually in 3/3. English required two retries; lab and Japanese required none. |
| **D. Stakeholder HOW** | Failed in 3/3: missing planned semantic items, invalid visible JSON, or a non-exact quote span. |
| **E. Stakeholder semantic validation/retry** | 11 rejected attempts and 8 semantic retries; every run exhausted the HOW attempt bound. |
| **F. Runtime/protocol limits** | Inspect ended `error` while runtime remained `active`; the propagated stakeholder error prevented terminal protocol state and scoring. Candidate limits were not the blocker. |
| **G. Evaluator/alignment** | No primary score exists, so evaluator/evidence/alignment weaknesses cannot be ranked. |
| **H. Scenario/profile difficulty** | The HOW blocker appeared for lab, English quotation, and Japanese quotation. This supports a cross-scenario structured-response blocker, not a scenario-specific score conclusion. |

Per-run primary and secondary categories are also stored in
`phase18.failure_analysis`.

## Explicit Phase 15 questions

1. **Does low eliminate the quotation EN stakeholder terminal failure?** No. It
   still ended with stakeholder semantic validation failure after the HOW retry
   bound.
2. **Does lab reach farther than Phase 15?** No. Phase 15 lab reached four
   accepted public responses and a 41-field score; Phase 18 lab stopped at its
   first response and had no score.
3. **Does quotation JA create a meaningful graph?** No. It asked one question,
   made no graph mutation, and produced no primary score.
4. **Are `candidate_did_not_ask_question` failures still present?** No, not in
   these three Phase 18 runs.
5. **Are tool errors still dominated by unknown concept refs and invalid
   evidence quote spans?** No tool errors occurred, so neither category was
   observed.
6. **Is evidence handling the dominant blocker now?** No conclusion about
   evidence can be made because no run reached scoring. The measured dominant
   blocker is stakeholder HOW.
7. **Are semantic correctness weaknesses systematic?** Not measurable in this
   phase because no 41-field score was produced; no semantic zero is inferred.

## Phase 19 decision

**Phase 19 primary target: stakeholder WHAT/HOW structured-response contract**
(with the measured blocker concentrated in the strict HOW parse/validation and
retry path). This is the only target selected from Phase 18 evidence. No Phase
19 implementation or tuning is included here.

## Safe artifact and validation record

Committed Phase 18 artifacts are:

- `calibration.json` — exact three-run manifest.
- `real-calibration-summary.json` — schema-v3 safe diagnostics and analysis.
- this `README.md` — protocol, results, A--H attribution, and decision.
- `tests/test_phase18_calibration.py` — manifest/schema/privacy tests.

The summary contains requested `low`, measured role-separated usage, safe
per-generation diagnostics, terminal classifications, and no prompts,
completions, reasoning text, exact private knowledge, credentials, or raw
`.eval` content. Historical Phase 14--17 files are not modified.
