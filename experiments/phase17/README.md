# Phase 17 stakeholder reasoning policy calibration

Phase 17 isolates Inspect's formal `GenerateConfig.reasoning_effort` on the
stakeholder model role. It compares `none`, `minimal`, and `low` without adding
a stakeholder token bound or changing prompts, schemas, validators, evaluators,
scenarios, profiles, candidate settings, retry policy, or graph semantics.
The existing benchmark default is not changed.

## Protocol

`calibration.json` contains exactly three one-epoch runs, one per policy:

- model for both roles: `openrouter/deepseek/deepseek-v4-flash-0731`
- scenario: `lab_sample_flow`
- stakeholder profile: `phase14-lab-technician`
- stakeholder seed: `1401`
- candidate generation: temperature `0.0` only
- stakeholder generation: temperature `0.0` plus the policy's
  `reasoning_effort`
- `max_interview_turns=1`
- `max_candidate_steps_per_turn=8`
- candidate `max_tokens=1024`
- no stakeholder `max_tokens`
- one epoch and one run per policy
- Inspect/API retry flag: `--max-retries 0`

The only independent variable is stakeholder `reasoning_effort`. Each provider
run was launched exactly once; no transient failure retry was needed. Raw logs
and temporary run configs remain outside the repository under
`/tmp/phase17-real-calibration/`.

## Requested versus effective behavior

Inspect accepted all three requested values through the formal run-config
renderer. The `.eval` logs did not contain explicit provider capability
metadata: `reasoning_supported`, documented/default effort, and supported-effort
information were unavailable, and no value is inferred. The safe summary records
`available: false` with `reason: not_recorded`.

Measured `reasoning_tokens` and `reasoning_share` are authoritative:

| requested effort | stakeholder output | reasoning | non-reasoning output | total | reasoning share |
| --- | ---: | ---: | ---: | ---: | ---: |
| `none` | 1,058 | 0 | 1,058 | 10,740 | 0.00% |
| `minimal` | 9,279 | 8,570 | 709 | 18,534 | 92.36% |
| `low` | 14,575 | 12,539 | 2,036 | 21,769 | 86.03% |

`none` therefore measured as no provider-reported reasoning in this run, but
that did not produce a valid HOW response. `minimal` and `low` still used
substantial reasoning; neither is treated as reasoning-free or as having an
unobserved provider capability guarantee. The `minimal` run had one provider
accounting contradiction (`reasoning_tokens=3,619` versus
`output_tokens=3,594` for one WHAT attempt); its derived non-reasoning value is
null for that attempt/phase and the safe warning is retained. Its role-level
aggregate remains valid (`8,570 <= 9,279`).

## WHAT/HOW quality and usage

In the tables below, accepted means a phase attempt passed to the next phase;
for HOW it additionally requires the authoritative accepted public ledger.
Accepted public response is reported separately. `null` non-reasoning values
mean that at least one measured generation in that phase had invalid or missing
accounting.

| effort | WHAT attempts accepted/rejected | HOW attempts accepted/rejected | valid WHAT | valid HOW | accepted public response | semantic retries / rejections | terminal class |
| --- | ---: | ---: | --- | --- | ---: | ---: | --- |
| `none` | 1 / 0 | 0 / 3 | yes | no | 0 | 2 / 3 | `stakeholder_semantic_validation_failure` |
| `minimal` | 1 / 2 | 1 / 0 | yes | yes | 1 | 2 / 2 | `interview_turn_limit` |
| `low` | 1 / 1 | 1 / 0 | yes | yes | 1 | 1 / 1 | `interview_turn_limit` |

| effort | phase | attempts | reasoning tokens | non-reasoning output | output tokens | total tokens | visible chars (sum) |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `none` | WHAT | 1 | 0 | 134 | 134 | 2,362 | 358 |
| `none` | HOW | 3 | 0 | 924 | 924 | 8,378 | 2,979 |
| `minimal` | WHAT | 3 | 7,250 | null | 7,656 | 14,424 | 1,729 |
| `minimal` | HOW | 1 | 1,320 | 303 | 1,623 | 4,110 | 1,299 |
| `low` | WHAT | 2 | 8,101 | 901 | 9,002 | 13,508 | 1,892 |
| `low` | HOW | 1 | 4,438 | 1,135 | 5,573 | 8,261 | 2,376 |

The `none` run produced a valid WHAT phase, then raised the existing
structured-response error after three invalid HOW JSON attempts. The
`minimal` and `low` runs each produced valid WHAT and HOW phases and one
accepted public response. Their `interview_turn_limit` class is an expected
one-turn calibration boundary (`max_turns_exhausted`), not a stakeholder
structured-response failure. Both still have `protocol_completed=false` and
are not claimed as complete benchmark runs.

Visible completion character sums were smallest for `none`, but its HOW was
invalid. `minimal` used 1,299 visible HOW characters in one accepted attempt;
`low` used 2,376. The per-generation safe records retain the individual
character counts and no completion text.

## Phase 16 comparison

Phase 16's eight-turn `lab_sample_flow` run measured stakeholder output `99,847`,
reasoning `96,852`, non-reasoning output `2,995`, and total `113,353` with a
97.00% reasoning share. Phase 17 intentionally uses one interview turn, so the
following directional reductions are not a causal apples-to-apples estimate of
a policy effect; they reflect both the policy and the smaller execution scope:

| effort | reasoning reduction vs Phase 16 | non-reasoning reduction | total-token reduction |
| --- | ---: | ---: | ---: |
| `none` | 100.00% | 64.67% | 90.53% |
| `minimal` | 91.15% | 76.33% | 83.65% |
| `low` | 87.05% | 32.02% | 80.80% |

The main diagnostic question was answered for the observed run: the zero-
reasoning `none` policy avoided the Phase 16 reasoning spike but did not preserve
HOW structured-response validity. `minimal` and `low` preserved the accepted
WHAT/HOW path, with `minimal` using 31.65% fewer stakeholder reasoning tokens
and 14.86% fewer total tokens than `low`; `low` had one fewer semantic retry.
No one-run result is statistically significant.

## Decision

**Recommended calibration candidate: `minimal`.** This is provisional, not a
production default. `none` is rejected as the leading candidate because HOW
failed completely. `minimal` and `low` both passed the observed structured
response and accepted-public-response checks; `minimal` is materially cheaper
in reasoning and total tokens, while `low` trades that cost for one fewer
semantic retry. The evidence does not establish stability across scenarios or
seeds, so confidence is low and the recommendation is not a statistical claim.

Next phase: run a three-scenario calibration with `minimal` as the leading
stakeholder policy candidate and retain `low` as a retry-quality control. Do not
add stakeholder `max_tokens` until that broader policy decision is complete.

## Safe artifacts and validation

`reasoning-calibration-summary.json` contains the requested policy, measured
role-separated usage, WHAT/HOW breakdown, acceptance/retry diagnostics,
capability-metadata availability, Phase 16 baseline, and the provisional
recommendation. It stores no raw reasoning, completions, prompts, semantic IDs,
`StakeholderKnowledge`, credentials, or raw `.eval` data. The Phase 16 artifact
is unchanged.
