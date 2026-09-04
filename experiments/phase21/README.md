# Phase 21: Candidate generation/runtime diagnosis

Phase 21 diagnoses Candidate-side generation outcomes without changing the
Candidate prompt strategy, tool surface, Stakeholder contract, or core
41-field evaluator.

## Diagnosis from prior runs

The new safe summarizer reclassified the Phase 20 logs at the generation
boundary:

- the `lab_sample_flow` run had two Candidate `max_tokens` generations;
  neither was a usable question, but neither was a normal empty completion;
- the `quotation_workflow_1` run reached the eight-step Candidate bound with
  tool-only generations and had recoverable `define_concept` and
  `set_node_property` tool errors;
- no Candidate provider error was observed in those persisted samples.

The historical terminal reason is not rewritten. The new per-generation
classification makes the two output-exhaustion events visible instead of
folding them into genuine no-question behavior.

## Implementation

- `inspect_adapter/candidate.py` classifies each `ModelOutput` as
  `question`, `tool_call`, `empty_completion`, `output_exhaustion`,
  `provider_error`, or `invalid_tool_call`. `max_tokens` and `model_length`
  take precedence over visible fragments.
- The multi-turn adapter persists explicit terminal reasons for output
  exhaustion and Candidate provider failures, catches provider exceptions as
  incomplete runs, and records a safe provider-error counter. It classifies a
  raw generation before explicitly executing tools, so a mixed truncated
  tool-bearing output cannot mutate the graph or complete the interview.
  Candidate step accounting remains one step per Generate invocation.
- Phase 14 safe summaries now retain per-generation turn/step indexes, stop
  reasons, configured token limits, reasoning policy, usage totals, tool names,
  tool-error counts, and typed outcomes. Run diagnostics include output-limit,
  provider, empty-completion, invalid-tool, and step-sequence counters.
- Aggregate diagnostics sum only safe numeric/type counters and exclude
  non-terminal samples marked `availability: unavailable`. No completion,
  reasoning text, tool arguments, Truth, private knowledge, or private
  semantic identifiers are persisted in these artifacts.

Stakeholder generation behavior and the 41-field `PrimaryEvaluation` remain
unchanged. Existing Stakeholder validation/retry tests remain the regression
contract.

## Controlled generation-policy experiment

`generation-policy-experiment.json` records three same-scenario Candidate
arms. The Candidate model, temperature, limits, stakeholder projection seed,
and strategy were held constant; the Candidate provider seed was intentionally
unset in every arm. A deterministic Inspect MockLLM stakeholder fixture isolated
the Candidate generation policy. The fixture was not used as benchmark quality
evidence.

| arm | max tokens | reasoning override | questions | output exhaustion | provider errors | Candidate reasoning tokens |
| --- | ---: | --- | ---: | ---: | ---: | ---: |
| baseline | 1024 | none | 8 | 0 | 0 | 1,148 |
| expanded | 2048 | none | 8 | 0 | 0 | 1,195 |
| expanded-low | 2048 | `low` | 8 | 0 | 0 | 496 |

All arms preserved the 41-field evaluation shape and had the same successful
question behavior. The provisional policy is `max_tokens=2048` with
`reasoning_effort=low`: it supplies a larger output budget while materially
reducing Candidate reasoning-token use. This is a generation-policy choice,
not an interview-strategy change. The arm experiment did not manufacture an
exhaustion event; the diagnostic classifier is validated by deterministic
fixtures and the reclassified Phase 20 logs.

## Provisional three-scenario calibration

`calibration.json` fixes the provisional Candidate policy, Stakeholder
`temperature=0.0`/`reasoning_effort=low`, provider retries `0`, eight interview
turns, and eight Candidate steps per turn. The launch protocol used model and
attempt timeouts of 60 seconds and a 300-second sample time limit.

`real-calibration-summary.json` is intentionally availability-aware:

- `lab_sample_flow` completed with a 41-field evaluation, one accepted
  non-empty WHAT, one accepted annotated HOW, zero Candidate output/provider
  failures, and zero Stakeholder contract failures;
- `quotation_workflow_1` and `quotation_workflow_1_ja` reached the sample time
  limit before a terminal protocol state and are marked **unavailable**;
- unavailable runs have no score or accepted-response metric and are excluded
  from aggregates. They are not converted to zero.

Raw `.eval` logs and rendered run configs remain only under `/tmp` and are not
part of the repository artifacts.
