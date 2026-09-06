# human_synthetic: Synthetic five-to-ten-minute human-check script

- source: `synthetic_human`
- source reference: `hand-authored practice script; no human participant was available in this run`
- human evaluation: `not_performed`
- note: This is the short script a user can run with a human later. The tool-call sequence is manually authored to exercise correction, unknown CRUD, a branch, a manual system, and a DONT_KNOW issue; it is not automatic extraction.

## Current business flow

- `source_boundary`: SOURCE → receive request [human_receive]
- `normal`: receive request [human_receive] → copy customer details into tracker [human_log_request]
- `normal`: copy customer details into tracker [human_log_request] → review request [human_review]
- `branch`: review request [human_review] → call on-call engineer [human_call_engineer] (when request is urgent)
- `branch`: review request [human_review] → schedule normal review [human_schedule_review] (when request is not urgent)
- `normal`: call on-call engineer [human_call_engineer] → update tracker after review [human_coordinator_update]
- `normal`: schedule normal review [human_schedule_review] → update tracker after review [human_coordinator_update]

## Process steps

- `human_receive` receive request; actor=intake coordinator [actor_intake]; inputs=request [data_request]; outputs=unset
- `human_log_request` copy customer details into tracker; actor=intake coordinator [actor_intake]; inputs=request [data_request]; outputs=request record [data_request_record]
- `human_review` review request; actor=dont_know; inputs=request record [data_request_record]; outputs=unset
- `human_call_engineer` call on-call engineer; actor=dont_know; inputs=request record [data_request_record]; outputs=unset
- `human_schedule_review` schedule normal review; actor=dont_know; inputs=request record [data_request_record]; outputs=unset
- `human_coordinator_update` update tracker after review; actor=coordinator [actor_coordinator]; inputs=request record [data_request_record]; outputs=request record [data_request_record]

## Systems

- `system_shared_inbox`: shared inbox (named)
- `system_tracker`: tracker (named)
- `system_manual`: manual work (manual)

## Process × system × data × CRUD

| process | system | data type | CRUD |
| --- | --- | --- | --- |
| receive request [human_receive] | shared inbox [system_shared_inbox] | request [data_request] | `unknown` |
| copy customer details into tracker [human_log_request] | tracker [system_tracker] | request record [data_request_record] | `create` |
| review request [human_review] | tracker [system_tracker] | request record [data_request_record] | `read` |
| call on-call engineer [human_call_engineer] | manual work [system_manual] | request record [data_request_record] | `unknown` |
| schedule normal review [human_schedule_review] | dont_know | request record [data_request_record] | `unknown` |
| update tracker after review [human_coordinator_update] | tracker [system_tracker] | request record [data_request_record] | `update` |

## Evidence and claims

- `claim:human_receive:activity` [provisional] process_step/human_receive/activity: receive request; evidence=ev_0001=h1[2:39]
- `claim:human_receive:actor` [provisional] process_step/human_receive/actor: actor_intake; evidence=ev_0001=h1[2:39]
- `claim:human_receive:inputs` [provisional] process_step/human_receive/inputs: ["data_request"]; evidence=ev_0001=h1[2:39]
- `claim:human_receive_inbox:crud` [provisional] resource_usage/human_receive_inbox/crud: unknown; evidence=ev_0002=h1[20:39]
- `claim:human_receive_inbox:system` [provisional] resource_usage/human_receive_inbox/system: system_shared_inbox; evidence=ev_0002=h1[20:39]
- `claim:human_receive_inbox:data_type` [provisional] resource_usage/human_receive_inbox/data_type: data_request; evidence=ev_0002=h1[20:39]
- `claim:human_log_request:activity` [provisional] process_step/human_log_request/activity: copy customer details into tracker; evidence=ev_0003=h2[7:81]
- `claim:human_log_request:actor` [provisional] process_step/human_log_request/actor: actor_intake; evidence=ev_0003=h2[7:81]
- `claim:human_log_request:inputs` [provisional] process_step/human_log_request/inputs: ["data_request"]; evidence=ev_0003=h2[7:81]
- `claim:human_log_request:outputs` [provisional] process_step/human_log_request/outputs: ["data_request_record"]; evidence=ev_0003=h2[7:81]
- `claim:human_log_tracker:crud` [provisional] resource_usage/human_log_tracker/crud: create; evidence=ev_0004=h2[57:81]
- `claim:human_log_tracker:system` [provisional] resource_usage/human_log_tracker/system: system_tracker; evidence=ev_0004=h2[57:81]
- `claim:human_log_tracker:data_type` [provisional] resource_usage/human_log_tracker/data_type: data_request_record; evidence=ev_0004=h2[57:81]
- `claim:human_review:activity` [provisional] process_step/human_review/activity: review request; evidence=ev_0005=h4[0:13]
- `claim:human_review:actor` [provisional] process_step/human_review/actor: dont_know; evidence=ev_0005=h4[0:13]
- `claim:human_review:inputs` [provisional] process_step/human_review/inputs: ["data_request_record"]; evidence=ev_0005=h4[0:13]
- `claim:human_review_tracker:crud` [rejected] resource_usage/human_review_tracker/crud: update; evidence=ev_0006=h4[16:52]
- `claim:human_review_tracker:system` [provisional] resource_usage/human_review_tracker/system: system_tracker; evidence=ev_0006=h4[16:52]
- `claim:human_review_tracker:data_type` [provisional] resource_usage/human_review_tracker/data_type: data_request_record; evidence=ev_0006=h4[16:52]
- `claim:human_call_engineer:activity` [provisional] process_step/human_call_engineer/activity: call on-call engineer; evidence=ev_0007=h3[26:53]
- `claim:human_call_engineer:actor` [provisional] process_step/human_call_engineer/actor: dont_know; evidence=ev_0007=h3[26:53]
- `claim:human_call_engineer:inputs` [provisional] process_step/human_call_engineer/inputs: ["data_request_record"]; evidence=ev_0007=h3[26:53]
- `claim:human_schedule_review:activity` [provisional] process_step/human_schedule_review/activity: schedule normal review; evidence=ev_0008=h3[65:91]
- `claim:human_schedule_review:actor` [provisional] process_step/human_schedule_review/actor: dont_know; evidence=ev_0008=h3[65:91]
- `claim:human_schedule_review:inputs` [provisional] process_step/human_schedule_review/inputs: ["data_request_record"]; evidence=ev_0008=h3[65:91]
- `claim:human_coordinator_update:activity` [provisional] process_step/human_coordinator_update/activity: update tracker after review; evidence=ev_0009=h6[0:52]
- `claim:human_coordinator_update:actor` [provisional] process_step/human_coordinator_update/actor: actor_coordinator; evidence=ev_0009=h6[0:52]
- `claim:human_coordinator_update:inputs` [provisional] process_step/human_coordinator_update/inputs: ["data_request_record"]; evidence=ev_0009=h6[0:52]
- `claim:human_coordinator_update:outputs` [provisional] process_step/human_coordinator_update/outputs: ["data_request_record"]; evidence=ev_0009=h6[0:52]
- `claim:human_source_receive:relation` [provisional] flow/human_source_receive/relation: SOURCE->human_receive; evidence=ev_0010=h1[2:19]
- `claim:human_receive_log:relation` [provisional] flow/human_receive_log/relation: human_receive->human_log_request; evidence=ev_0011=h2[0:32]
- `claim:human_log_review:relation` [provisional] flow/human_log_review/relation: human_log_request->human_review; evidence=ev_0012=h4[0:13]
- `claim:human_review_urgent:relation` [provisional] flow/human_review_urgent/relation: human_review->human_call_engineer; evidence=ev_0013=h3[0:24]
- `claim:human_review_urgent:condition` [provisional] flow/human_review_urgent/condition: request is urgent; evidence=ev_0013=h3[0:24]
- `claim:human_review_normal:relation` [provisional] flow/human_review_normal/relation: human_review->human_schedule_review; evidence=ev_0014=h3[55:91]
- `claim:human_review_normal:condition` [provisional] flow/human_review_normal/condition: request is not urgent; evidence=ev_0014=h3[55:91]
- `claim:human_call_update:relation` [provisional] flow/human_call_update/relation: human_call_engineer->human_coordinator_update; evidence=ev_0015=h6[16:52]
- `claim:human_schedule_update:relation` [provisional] flow/human_schedule_update/relation: human_schedule_review->human_coordinator_update; evidence=ev_0016=h6[16:52]
- `claim:human_manual_call:crud` [provisional] resource_usage/human_manual_call/crud: unknown; evidence=ev_0017=h8[0:63]
- `claim:human_manual_call:system` [provisional] resource_usage/human_manual_call/system: system_manual; evidence=ev_0017=h8[0:63]
- `claim:human_manual_call:data_type` [provisional] resource_usage/human_manual_call/data_type: data_request_record; evidence=ev_0017=h8[0:63]
- `claim:human_schedule_unknown:crud` [provisional] resource_usage/human_schedule_unknown/crud: unknown; evidence=ev_0018=h3[67:91]
- `claim:human_schedule_unknown:system` [provisional] resource_usage/human_schedule_unknown/system: dont_know; evidence=ev_0018=h3[67:91]
- `claim:human_schedule_unknown:data_type` [provisional] resource_usage/human_schedule_unknown/data_type: data_request_record; evidence=ev_0018=h3[67:91]
- `claim:human_review_tracker:crud:revision1` [confirmed] resource_usage/human_review_tracker/crud: read; evidence=ev_0019=h5[0:56]; supersedes `claim:human_review_tracker:crud`
- `claim:human_coordinator_tracker_update:crud` [provisional] resource_usage/human_coordinator_tracker_update/crud: update; evidence=ev_0021=h6[0:52]
- `claim:human_coordinator_tracker_update:system` [provisional] resource_usage/human_coordinator_tracker_update/system: system_tracker; evidence=ev_0021=h6[0:52]
- `claim:human_coordinator_tracker_update:data_type` [provisional] resource_usage/human_coordinator_tracker_update/data_type: data_request_record; evidence=ev_0021=h6[0:52]

## Open questions

- `question:human_approval_unknown` [open] Is customer approval recorded anywhere, and who confirms it? (target: human_review)

## Contradictions

- `contradiction:human_review_correction` [resolved]: claim:human_review_tracker:crud, claim:human_review_tracker:crud:revision1

## Corrections

- `claim:human_review_tracker:crud` → `claim:human_review_tracker:crud:revision1`; old claim is rejected, new value is read

## Completion

- status: `ended`
- termination reason: `short practice interview ended after the planned questions`
- unresolved: question:human_approval_unknown
- stakeholder confirmed: `False`
- content completeness: `incomplete`
