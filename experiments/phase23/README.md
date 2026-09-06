# Phase 23: state-aware follow-up updates

## Scope

This change makes the latest typed `InterviewState` visible at every model
`generate()` call without adding snapshots to the provider history or the
checkpoint.  The display is built from the existing
`inspect_interview_state`/Pydantic output and deliberately omits evidence.  It
contains the current process projection, related records, active claim IDs,
claim values and information states, open questions, and contradictions.

The Japanese agent/tool guidance now distinguishes `UNSET` (not yet heard),
`ABSENT` (explicitly does not exist), `DONT_KNOW` (the user does not know),
and `value`.  It requires later actor/input/output/correction details to use
`revise_record` on the existing record, forbids turning activity nouns into
inputs/outputs, requires `unknown` CRUD when the operation is not explicit, and
requires an explicit next-step relation to use `connect_process_steps`.

The fixed public acceptance conversation used in every run was:

1. `申請内容を確認する業務です。`
2. `その確認を担当するのは経理です。`
3. `訂正です。その確認の担当は経理ではなく営業です。`
4. `確認の次に、別の処理として総務が結果を保管します。`

The first process was saved after turn 1.  A separate process resumed from that
checkpoint and supplied turns 2–4.  These are public synthetic inputs; the
reports and state JSON files preserve the actual assistant responses and state
at turn 1 and after turn 4.  They are not a general interview-quality score.

## Model protocol

- Model: `openrouter/openai/gpt-4o-mini`
- `max_tokens=1024`, `max_tool_rounds=4`, `max_tool_calls=8`
- `timeout=60`, `max_retries=0`, `parallel_tool_calls=false`
- No `--complete`; the controller stopped after the four fixed utterances.
- All runs exited 0 and had no provider error, truncation, or timeout.
- The normal before/after comparison is `before` versus final `after-v5`.
  `after-v4` is the one additional direct prompt-fix trial permitted after the
  first post-change run.

| run | code SHA-256 (`interview_agent.py`) | prompt | purpose |
| --- | --- | --- | --- |
| before | `02e09f691d687c1872744c19a708e4c8385e4a1dc6d98aa9099d460e7fe51948` | `interview-state-agent.ja.v3` | base commit `8ad515a3360ea6adf14a145c6b13489cf479400f` |
| after-v4 | `58d8e8057fe4e115ff428a7b761b1f4af2d768b5e35306d8ae9571bd5ab05d56` | `interview-state-agent.ja.v4` | state snapshot and update-boundary guidance |
| after-v5 | `1a936477bdfde680c55666f679dea52a5814af64cb901198324e57f12d092c70` | `interview-state-agent.ja.v5` | direct prompt refinement for field evidence and explicit flow |

## Expected versus observed state

| stage | expected | before | final after-v5 |
| --- | --- | --- | --- |
| 1 | one confirmation step; actor/input/output `UNSET`; no invented actor | one step, but actor was `ABSENT`; two claims | one step; actor/input/output `UNSET`; one activity claim |
| 2 | same step ID; actor becomes accounting | added multiple new steps and claims | model reported a duplicate-step and revision failure; review actor stayed `UNSET` |
| 3 | same step ID; actor becomes sales; old accounting claim and new evidence retained | more duplicate steps; no correction history | revision again failed; no actor correction was recorded |
| 4 | store step by general affairs and explicit review→store order; review remains sales | six steps, no flow | two steps, store actor and review→store flow were recorded, but review actor was still `UNSET` |

The intermediate `after-v4` run showed the other side of the remaining model
variance: it preserved one review step, corrected accounting to sales with
claim history, and added the store step, but inferred an input named
`申請内容` from an activity noun and omitted the flow.  The final `after-v5`
run fixed those two extraction behaviors in this sample but failed the actor
updates.  No model output was hand-edited.  Therefore the deterministic
contract is improved and the before run's duplicate-generation behavior is
not reproduced, but the real-model sample does **not** satisfy all four
semantic expectations; the residual is reported rather than hidden.

## Artifacts

Each run directory contains `state-u1.json`, `report-u1.md`,
`state-final.json`, `report-final.md`, and the final checkpoint.  The reports
contain the exact public assistant messages and ordered public conversation;
the JSON contains the corresponding typed state, claims, evidence references,
and correction/flow projections.  No raw provider response, hidden reasoning,
or credential is stored.

## Offline acceptance coverage

`tests/test_interview_agent.py` verifies that the actual captured generation
input contains the current process and active claim states, that the snapshot
refreshes after a successful tool update, that checkpoint resume supplies both
saved business state and public conversation, and that the fixed four-turn
executor contract preserves one review step, the accounting→sales correction
history, the store step, and the explicit flow.  Those tests use deterministic
MockLLM tool selections only as adapter/executor contract tests; they are not
substitutes for the real-model comparison above.
