# Phase 25: final `revise_record` schema after the Inspect boundary

This artifact records the deterministic regression and one post-fix real-model
trial for the `ToolParams` conversion bug. It contains only the public
synthetic conversation, public tool arguments, typed receipts/errors, and
state identifiers. It does not contain provider responses, hidden reasoning,
or credentials.

## Fixed conversation

1. `u1`: `申請内容を確認する業務です。`
2. `u2`: `その確認を担当するのは経理です。`
3. `u3`: `訂正です。その確認の担当は経理ではなく営業です。`
4. `u4`: `確認の次に、別の処理として総務が結果を保管します。`

The first process saved `checkpoint-u1.json`. The second process loaded that
checkpoint before handling later utterances.

## Deterministic reproduction and fix

Before the fix, Pydantic and `_agent_tool_schema` retained
`ActorChange.field` as `{"const": "actor", ...}`. The final
`ToolParams.model_validate(...).model_dump(..., exclude_none=True)` changed
that field to an unconstrained string. `jsonschema` therefore accepted an
`actor` field with a `SystemInput` value containing `kind: "named"`, even
though the intermediate schema rejected it.

The adapter now converts string `const` constraints to singleton `enum`
constraints before `ToolParams`. It recursively handles nested schemas and
fails explicitly for non-string or contradictory `const`/`enum` constraints.
`tool-schema.json` is the actual provider-facing `ToolDef.parameters` output
from the post-fix agent.

The regression tests validate the final schema from the real Agent tool, not
only the intermediate Pydantic schema. They cover all eight field/value
variants, valid nullable/state forms, extra properties, unknown fields, and
cross-variant values such as actor + `SystemInput`, actor + `CrudInput`, and
inputs + `EntityInput`.

## Real-model protocol

- Model: `openrouter/openai/gpt-4o-mini`
- `max_tokens=1024`
- `max_tool_rounds=4`
- `max_tool_calls=8`
- `timeout=60`
- `max_retries=0`
- `parallel_tool_calls=false`

The recorder is `../record_trial.py`. It saves only public tool arguments,
call IDs/order, receipts or errors, and state identifiers after each turn.

## Recorded result

The initial turn succeeded as required:

- `record_process_step` created exactly `step:check_application`.
- The actor, inputs, and outputs remained `UNSET`.
- The only claim was the provisional activity claim.

The recorded resume process did not reach `u3` or `u4`. At `u2`, the model
selected `revise_record`, but repeatedly used the existing activity claim ID
as `replacement_id` (and once attempted to revise the activity itself). The
Executor returned the recorded error:

> `replacement claim ID already exists: 'claim:step:check_application:activity'`

The model then attempted to re-record the existing process step. After four
model rounds the bounded run ended with `model_call_limit`. The actor remained
`UNSET`; no system, data type, or CRUD was added. The exact public arguments,
call IDs, receipts, errors, and state identifiers are in `invocations.json`,
with the terminal failure in `failure-u2.json` and the state/report in
`state-failure-u2.json` and `report-failure-u2.md`.

This semantic trial therefore did **not** meet the four-turn acceptance target.
The observed failure is an executor operation/identifier-selection problem,
not a final-schema `const` loss: the recorded actor calls had the correct
`EntityInput` shape and were rejected because of the reused replacement ID.
It is not asserted to be the same cause as Phase 24's unrecorded failure.

## Code identity

`code-sha256.txt` records the review base commit and hashes of the modified
working-tree files used for this trial. The final commit SHA is reported with
the repository result after validation and push.
