# Phase 15 DeepSeek V4 Flash calibration

Baseline: `575fb087cfe191e6c991717c6ecc8015e720a83b`.

Phase 15 repairs the candidate Inspect tool surface that Phase 14's
OpenAI-compatible provider rejected. The repair removes the three generic
`update_*` candidate tools, splits scalar and list-valued node-property writes,
and keeps explicit `set_*_absent`/`set_*_dont_know` operations. Evidence is
attached through the dedicated typed `attach_evidence` tool. Core graph and
evaluator semantics are unchanged.

## Preflight

The exact OpenRouter model was listed and accepted one tool-bearing chat request
containing the complete 19-tool candidate schema surface:

- model: `openrouter/deepseek/deepseek-v4-flash-0731`
- provider API model ID: `deepseek/deepseek-v4-flash-0731`
- schema result: accepted
- response content and credentials: not saved

The safe record is `schema-preflight.json`. The deterministic schema tests are
in `tests/test_phase15_tool_schemas.py`; they recursively require explicit
primitive/array/object types, typed array items, `additionalProperties: false`
for objects, and consistent `required` fields.

## Required calibration

`calibration.json` fixes the three historical scenarios, profiles, seeds,
limits, temperature, and one epoch. Only the candidate and stakeholder model
fields differ from the Phase 14 manifest. Each scenario was launched exactly
once with `--max-retries 0`:

| run | scenario | profile | seed | failure class | candidate generations | stakeholder generations | accepted responses | semantic retries / rejections | tool errors | score |
| ---: | --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | --- |
| 0 | `lab_sample_flow` | `phase14-lab-technician` | 1401 | `tool/runtime_failure` | 16 | 12 | 4 | 4 / 4 | 7 | 41 fields |
| 1 | `quotation_workflow_1` | `phase14-sales-owner` | 1402 | `stakeholder_semantic_validation_failure` | 2 | 5 | 0 | 3 / 4 | 0 | unavailable |
| 2 | `quotation_workflow_1_ja` | `phase14-sales-owner-ja` | 1403 | `candidate_generation_failure` | 3 | 4 | 1 | 2 / 2 | 0 | 41 fields |

The safe aggregate and per-run record is
`real-calibration-summary.json`. Raw `.eval` logs remain outside the
repository under `/tmp/phase15-real-calibration/`.

## Quality analysis

The provider-schema blocker was cleared: the preflight succeeded, and the
first calibration reached candidate graph tools. Measurement quality was still
poor and no run completed the protocol:

- Completion, protocol-pass, and reconstruction-pass rates were all `0/3`.
- Of the two runs with scores, run 0 created a valid graph with node and edge
  precision/recall of `1.0`, but had semantic correctness of `0.0` for
  conditions and rationale and `0.25` for system/reads/writes; evidence and
  reconstruction both failed. Its seven recoverable tool errors comprised
  four unknown-concept references and three non-exact evidence-quote spans.
- Run 2 produced no graph and had zero node/edge precision or recall. Run 1
  terminated before a primary evaluation was available.
- Stakeholder semantic validation rejected attempts in all three scenarios:
  10 rejections and 9 semantic retries in total, including a terminal
  three-attempt invalid-response failure in run 1. Five responses were
  accepted. Provider-reported total usage was 675,815 tokens; cost was not
  recorded and is not estimated.
- The candidate failed to ask a question at the required boundary in runs 0
  and 2. This is reported as observed protocol behavior, not corrected by a
  prompt, evaluator, scenario, or score-based rerun.

**Next priority:** harden the stakeholder structured-response runtime path for
this provider—bounded generation plus clearer parse/semantic-validation
classification—before interpreting candidate strategy or scenario quality.
This is supported by the cross-scenario rejection/retry pattern and run 1's
terminal failure, and does not require changing benchmark prompts, evaluators,
or scenarios.

No credentials, private stakeholder knowledge, full prompts, or raw logs are
stored in the Phase 15 artifacts. Phase 14 artifacts remain unchanged.
