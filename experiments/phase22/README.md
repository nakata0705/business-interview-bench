# Phase 22: public conversation checkpoint/resume

## Scope

This change keeps the public assistant question in the text-interview
checkpoint without persisting Inspect provider messages. The checkpoint
schema is `business_interview.interview_agent.v3`; the prompt identifier is
`interview-state-agent.ja.v3`. `PublicConversationMessage` stores only a
stable message ID, `user`/`assistant` role, public body, sequence, the
`InterviewState.Utterance` reference for user messages, and an optional
`reply_to` link to the immediately preceding assistant message.

A `reply_to` link is conversational context, not evidence or proof that a
short answer agrees with every point in a multi-part question. Evidence
candidates still come only from user `Utterance` records. The report prints
the ordered public conversation and links evidence from a short answer back to
the question when that link exists.

## Regression and offline verification

At the base commit `275181e73fbb6564b2288fdf1f66543c73d8cb1b`, the new regression
scenario failed: after saving a question and restoring the agent, the captured
`generate()` input for the next `はい` contained the two user messages but not
the question. The final test
`test_checkpoint_round_trip_preserves_public_question_for_short_answer` now
captures the actual model input and verifies the restored order.

The MockLLM suite also verifies correction through the existing executor,
rejection of an assistant question as an evidence candidate, repeated
save/restore without duplicate messages or tool execution, and omission of
truncated/internal provider output from the public ledger.

## Real-provider attempt

Credentials were available through the pre-existing environment
(`OPENROUTER_API_KEY` was present; its value is not recorded). The allowed
initial attempt and one direct adapter-schema retry were made with the same
model and settings. The resume step below was the continuation of the
successful retry, not another independent retry.

- Model: `openrouter/openai/gpt-4o-mini`
- Settings: `max_tokens=512`, `max_tool_rounds=4`, `max_tool_calls=8`,
  `timeout=60`, `max_retries=0`, `parallel_tool_calls=false`
- Input: `申請内容を確認する業務です。`
- Prompt: `interview-state-agent.ja.v3`
- Initial attempt code identifier:
  `src/business_interview_bench/interview_agent.py` SHA-256
  `cbd506e79b7de7fa13058b702be70025f65bf96f3b083c8a275a9ffc7b0a6ed5`
- Initial result: exit status 2 before the first model completion. The
  OpenRouter/OpenAI endpoint rejected the existing `inspect_interview_state`
  tool schema because optional `target_ids` was not included in the provider
  required array. The checkpoint finally saved the user utterance only, with
  `execution_status=technical_failure` and
  `last_failure_kind=communication_failure`; no assistant message was saved.
- Direct fix: the adapter now marks every object property required in the
  strict provider schema while retaining nullable/default Pydantic parsing.
  This does not change the seven core operation contracts.
- Retry result: exit status 0. The model returned this public response:
  `「申請内容を確認する業務」が新たに記録されました。次に確認したい内容はありますか？`
  The retry checkpoint contained one user and one assistant public message,
  one process step, and four provisional claims.
- Resume input: the actual response to that question was
  `確認を担当するのは経理です。` (the question was open-ended, so a fixed
  unrelated `はい` was not substituted).
- Resume result: exit status 0. The resumed checkpoint contained four ordered
  public messages; the answer had `reply_to=public:assistant:0001`, and the
  model-selected update used the exact `u2` text as evidence for the
  accounting actor. The model also created an additional process step and
  inferred a stakeholder actor on the first turn, so this is evidence of
  public-context continuity and executor reachability, not a claim of
  extraction-quality or semantic-interview success.
- Retry code identifier:
  `src/business_interview_bench/interview_agent.py` SHA-256
  `f5972102f9448f9694516ac07c17b2db240a2d7505cdae48bd02801af77ef91e`.

No fixed question or answer was substituted after the successful retry. Raw
provider output and credential material remain outside the repository.
