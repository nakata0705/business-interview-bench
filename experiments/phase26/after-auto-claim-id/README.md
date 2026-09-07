# Phase 26: Executor-generated `revise_record` Claim IDs

This artifact records the deterministic Phase 25 replay and one constrained
four-utterance real-model trial after removing `replacement_id` from the
public `revise_record` contract. It contains only public synthetic
conversation text, public tool arguments, typed receipts/errors, and state
identifiers. It does not contain provider responses, hidden reasoning, or
credentials.

## Fixed conversation

1. `u1`: `申請内容を確認する業務です。`
2. `u2`: `その確認を担当するのは経理です。`
3. `u3`: `訂正です。その確認の担当は経理ではなく営業です。`
4. `u4`: `確認の次に、別の処理として総務が結果を保管します。`

The first process saved `checkpoint-u1.json`. The second process loaded that
checkpoint before handling later utterances.

## Implementation and deterministic replay

`revise_record` no longer accepts or publishes `replacement_id`. The
Executor deterministically generates `claim:{record_id}:{field}` and then
`:revisionN` IDs while checking every persisted Claim ID, including rejected
history. It preserves `expected_claim_id`, `revised_from`, `supersedes`, and
atomic state mutation behavior.

`deterministic-replay.json` replays the Phase 25 failed `u2` invocation after
removing only `replacement_id`. The replay succeeds, creates
`claim:step:check_application:actor`, creates `actor:accounting`, and leaves
the existing activity claim unchanged.

The regression suite also covers revision-history preservation, collision-free
IDs across rejected history, state round-trip continuation, expected-claim
validation, invalid typed updates, atomic failure behavior, legacy
`replacement_id` rejection, and final provider-schema typing.

## Real-model protocol

- Model: `openrouter/openai/gpt-4o-mini`
- `max_tokens=1024`
- `max_tool_rounds=4`
- `max_tool_calls=8`
- `timeout=60`
- `max_retries=0`
- `parallel_tool_calls=false`

The recorder is `../../phase25/record_trial.py`. It saves only public tool
arguments, call IDs/order, receipts or errors, and state identifiers after
each turn. `tool-schema.json` is the final Agent `ToolDef.parameters` output;
its `revise_record` properties contain no `replacement_id`.

## Recorded result

All four public utterances were processed and the model no longer supplied
`replacement_id`:

- `u1`: created `step:check_application` with only its activity claim.
- `u2`: `revise_record` created `claim:step:check_application:actor` and
  `actor:accounting` without a replacement ID. The model also made one
  redundant `record_process_step` call, which failed deterministically because
  the step already existed; the failed call did not change state.
- `u3`: `revise_record` created
  `claim:step:check_application:actor:revision1`, rejected the accounting
  claim, and set `supersedes`/`revised_from` correctly.
- `u4`: created `step:store_results` with actor `actor:general_affairs`.

The model did not call `connect_flow` for the sequencing phrase in `u4`, so
the final state has no flow edge. The bounded run therefore records successful
ID-generation/history behavior and four-turn processing, but does not claim
full semantic acceptance of the flow-edge requirement. This model behavior is
separate from the schema and Executor fix and is not asserted to be the same
cause as Phase 24's failure.

## Code identity

`code-sha256.txt` records the review base commit and hashes of the working-tree
files used for this trial.
