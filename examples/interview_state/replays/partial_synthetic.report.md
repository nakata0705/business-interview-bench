# partial_synthetic: Synthetic interrupted intake interview

- source: `synthetic_partial`
- source reference: `hand-authored fixture; no raw Phase 20/21 conversation was committed`
- human evaluation: `not_performed`
- note: A short synthetic case stands in for the unavailable failed/partial provider transcript. It intentionally ends with an open question and unknown CRUD; it is not an existing-log replay.

## Current business flow

- `normal`: receive request [partial_receive] → review request [partial_review]

## Process steps

- `partial_receive` receive request; actor=intake coordinator [actor_intake]; inputs=request [data_request]; outputs=unset
- `partial_review` review request; actor=dont_know; inputs=request [data_request]; outputs=unset

## Systems

- `system_email`: email (named)
- `system_intake_sheet`: intake sheet (named)

## Process × system × data × CRUD

| process | system | data type | CRUD |
| --- | --- | --- | --- |
| receive request [partial_receive] | email [system_email] | request [data_request] | `unknown` |
| review request [partial_review] | intake sheet [system_intake_sheet] | request [data_request] | `unknown` |

## Evidence and claims

- `claim:partial_receive:activity` [provisional] process_step/partial_receive/activity: receive request; evidence=ev_0001=p1[0:34]
- `claim:partial_receive:actor` [provisional] process_step/partial_receive/actor: actor_intake; evidence=ev_0001=p1[0:34]
- `claim:partial_receive:inputs` [provisional] process_step/partial_receive/inputs: ["data_request"]; evidence=ev_0001=p1[0:34]
- `claim:partial_review:activity` [provisional] process_step/partial_review/activity: review request; evidence=ev_0002=p2[0:20]
- `claim:partial_review:actor` [provisional] process_step/partial_review/actor: dont_know; evidence=ev_0002=p2[0:20]
- `claim:partial_review:inputs` [provisional] process_step/partial_review/inputs: ["data_request"]; evidence=ev_0002=p2[0:20]
- `claim:partial_receive_review:relation` [provisional] flow/partial_receive_review/relation: partial_receive->partial_review; evidence=ev_0003=p2[21:54]
- `claim:partial_receive_email:crud` [provisional] resource_usage/partial_receive_email/crud: unknown; evidence=ev_0004=p1[18:34]
- `claim:partial_receive_email:system` [provisional] resource_usage/partial_receive_email/system: system_email; evidence=ev_0004=p1[18:34]
- `claim:partial_receive_email:data_type` [provisional] resource_usage/partial_receive_email/data_type: data_request; evidence=ev_0004=p1[18:34]
- `claim:partial_review_sheet:crud` [provisional] resource_usage/partial_review_sheet/crud: unknown; evidence=ev_0005=p3[14:85]
- `claim:partial_review_sheet:system` [provisional] resource_usage/partial_review_sheet/system: system_intake_sheet; evidence=ev_0005=p3[14:85]
- `claim:partial_review_sheet:data_type` [provisional] resource_usage/partial_review_sheet/data_type: data_request; evidence=ev_0005=p3[14:85]

## Open questions

- `question:partial_review_crud` [open] Does reviewing create a new record or update the intake sheet? (target: partial_review, partial_review_sheet)

## Contradictions

- (none)

## Corrections

- (none)

## Completion

- status: `ended`
- termination reason: `time limit before review ownership and CRUD could be confirmed`
- unresolved: question:partial_review_crud
- stakeholder confirmed: `False`
- content completeness: `incomplete`
