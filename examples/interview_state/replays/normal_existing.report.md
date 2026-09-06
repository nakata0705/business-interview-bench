# normal_existing: Seed 9004 public observation replay

- source: `existing_public_fixture`
- source reference: `src/business_interview/replay_data/seed9004/evaluation_context.json`
- human evaluation: `not_applicable`
- note: The repository stores these exact public stakeholder observations and a completed protocol flag, but not the full assistant transcript. This is a replay of the available public observation fixture, not a claim that the omitted transcript was reconstructed.

## Current business flow

- `source_boundary`: SOURCE → receive quotation request [step_receive_request]
- `normal`: receive quotation request [step_receive_request] → check customer information [step_check_customer]
- `normal`: check customer information [step_check_customer] → create quotation [step_create_quotation]
- `branch`: create quotation [step_create_quotation] → approve high-value quotation [step_approve_high_value] (when amount over 1,000,000 yen)
- `branch`: create quotation [step_create_quotation] → send quotation to customer [step_send_quotation] (when amount at or below 1,000,000 yen)
- `branch`: create quotation [step_create_quotation] → send month-end summary to Accounting [step_send_month_end_summary] (when month-end)
- `normal`: approve high-value quotation [step_approve_high_value] → send quotation to customer [step_send_quotation]
- `sink_boundary`: send quotation to customer [step_send_quotation] → SINK
- `sink_boundary`: send month-end summary to Accounting [step_send_month_end_summary] → SINK

## Process steps

- `step_receive_request` receive quotation request; actor=sales employee [actor_sales]; inputs=quotation request [data_quotation_request]; outputs=unset
- `step_check_customer` check customer information; actor=sales employee [actor_sales]; inputs=customer information [data_customer_information]; outputs=unset
- `step_create_quotation` create quotation; actor=sales employee [actor_sales]; inputs=customer information [data_customer_information], pricing information [data_pricing_information]; outputs=quotation [data_quotation]
- `step_approve_high_value` approve high-value quotation; actor=manager [actor_manager]; inputs=quotation [data_quotation]; outputs=unset
- `step_send_quotation` send quotation to customer; actor=sales employee [actor_sales]; inputs=quotation [data_quotation]; outputs=unset
- `step_send_month_end_summary` send month-end summary to Accounting; actor=sales employee [actor_sales]; inputs=unset; outputs=month-end summary [data_month_end_summary]

## Systems

- `system_crm`: CRM (named)
- `system_quoting`: quoting system (named)
- `system_email`: email (named)

## Process × system × data × CRUD

| process | system | data type | CRUD |
| --- | --- | --- | --- |
| check customer information [step_check_customer] | CRM [system_crm] | customer information [data_customer_information] | `read` |
| create quotation [step_create_quotation] | quoting system [system_quoting] | quotation [data_quotation] | `create` |
| send quotation to customer [step_send_quotation] | email [system_email] | quotation [data_quotation] | `unknown` |
| approve high-value quotation [step_approve_high_value] | dont_know | quotation [data_quotation] | `unknown` |
| send month-end summary to Accounting [step_send_month_end_summary] | dont_know | month-end summary [data_month_end_summary] | `unknown` |

## Evidence and claims

- `claim:step_receive_request:activity` [confirmed] process_step/step_receive_request/activity: receive quotation request; evidence=ev_0001=obs_3[6:91]
- `claim:step_receive_request:actor` [confirmed] process_step/step_receive_request/actor: actor_sales; evidence=ev_0001=obs_3[6:91]
- `claim:step_receive_request:inputs` [confirmed] process_step/step_receive_request/inputs: ["data_quotation_request"]; evidence=ev_0001=obs_3[6:91]
- `claim:step_check_customer:activity` [provisional] process_step/step_check_customer/activity: check customer information; evidence=ev_0002=obs_12[14:55]
- `claim:step_check_customer:actor` [provisional] process_step/step_check_customer/actor: actor_sales; evidence=ev_0002=obs_12[14:55]
- `claim:step_check_customer:inputs` [provisional] process_step/step_check_customer/inputs: ["data_customer_information"]; evidence=ev_0002=obs_12[14:55]
- `claim:step_create_quotation:activity` [provisional] process_step/step_create_quotation/activity: create quotation; evidence=ev_0003=obs_23[8:109]
- `claim:step_create_quotation:actor` [provisional] process_step/step_create_quotation/actor: actor_sales; evidence=ev_0003=obs_23[8:109]
- `claim:step_create_quotation:inputs` [provisional] process_step/step_create_quotation/inputs: ["data_customer_information","data_pricing_information"]; evidence=ev_0003=obs_23[8:109]
- `claim:step_create_quotation:outputs` [provisional] process_step/step_create_quotation/outputs: ["data_quotation"]; evidence=ev_0003=obs_23[8:109]
- `claim:step_approve_high_value:activity` [provisional] process_step/step_approve_high_value/activity: approve high-value quotation; evidence=ev_0004=obs_33[67:112]
- `claim:step_approve_high_value:actor` [provisional] process_step/step_approve_high_value/actor: actor_manager; evidence=ev_0004=obs_33[67:112]
- `claim:step_approve_high_value:inputs` [provisional] process_step/step_approve_high_value/inputs: ["data_quotation"]; evidence=ev_0004=obs_33[67:112]
- `claim:step_send_quotation:activity` [provisional] process_step/step_send_quotation/activity: send quotation to customer; evidence=ev_0005=obs_53[14:57]
- `claim:step_send_quotation:actor` [provisional] process_step/step_send_quotation/actor: actor_sales; evidence=ev_0005=obs_53[14:57]
- `claim:step_send_quotation:inputs` [provisional] process_step/step_send_quotation/inputs: ["data_quotation"]; evidence=ev_0005=obs_53[14:57]
- `claim:step_send_month_end_summary:activity` [provisional] process_step/step_send_month_end_summary/activity: send month-end summary to Accounting; evidence=ev_0006=obs_33[214:254]
- `claim:step_send_month_end_summary:actor` [provisional] process_step/step_send_month_end_summary/actor: actor_sales; evidence=ev_0006=obs_33[214:254]
- `claim:step_send_month_end_summary:outputs` [provisional] process_step/step_send_month_end_summary/outputs: ["data_month_end_summary"]; evidence=ev_0006=obs_33[214:254]
- `claim:flow_source_receive:relation` [provisional] flow/flow_source_receive/relation: SOURCE->step_receive_request; evidence=ev_0007=obs_3[6:24]
- `claim:flow_receive_check:relation` [provisional] flow/flow_receive_check/relation: step_receive_request->step_check_customer; evidence=ev_0008=obs_12[0:56]
- `claim:flow_check_create:relation` [provisional] flow/flow_check_create/relation: step_check_customer->step_create_quotation; evidence=ev_0009=obs_23[0:28]
- `claim:flow_create_approve:relation` [provisional] flow/flow_create_approve/relation: step_create_quotation->step_approve_high_value; evidence=ev_0010=obs_33[30:65]
- `claim:flow_create_approve:condition` [provisional] flow/flow_create_approve/condition: amount over 1,000,000 yen; evidence=ev_0010=obs_33[30:65]
- `claim:flow_create_send_low:relation` [provisional] flow/flow_create_send_low/relation: step_create_quotation->step_send_quotation; evidence=ev_0011=obs_33[114:148]
- `claim:flow_create_send_low:condition` [provisional] flow/flow_create_send_low/condition: amount at or below 1,000,000 yen; evidence=ev_0011=obs_33[114:148]
- `claim:flow_create_month_end:relation` [provisional] flow/flow_create_month_end/relation: step_create_quotation->step_send_month_end_summary; evidence=ev_0012=obs_33[192:210]
- `claim:flow_create_month_end:condition` [provisional] flow/flow_create_month_end/condition: month-end; evidence=ev_0012=obs_33[192:210]
- `claim:flow_approve_send:relation` [provisional] flow/flow_approve_send/relation: step_approve_high_value->step_send_quotation; evidence=ev_0013=obs_60[5:103]
- `claim:flow_send_sink:relation` [provisional] flow/flow_send_sink/relation: step_send_quotation->SINK; evidence=ev_0014=obs_60[286:338]
- `claim:flow_summary_sink:relation` [provisional] flow/flow_summary_sink/relation: step_send_month_end_summary->SINK; evidence=ev_0015=obs_33[214:254]
- `claim:usage_check_customer:crud` [provisional] resource_usage/usage_check_customer/crud: read; evidence=ev_0016=obs_12[14:55]
- `claim:usage_check_customer:system` [provisional] resource_usage/usage_check_customer/system: system_crm; evidence=ev_0016=obs_12[14:55]
- `claim:usage_check_customer:data_type` [provisional] resource_usage/usage_check_customer/data_type: data_customer_information; evidence=ev_0016=obs_12[14:55]
- `claim:usage_create_quotation:crud` [provisional] resource_usage/usage_create_quotation/crud: create; evidence=ev_0017=obs_23[8:50]
- `claim:usage_create_quotation:system` [provisional] resource_usage/usage_create_quotation/system: system_quoting; evidence=ev_0017=obs_23[8:50]
- `claim:usage_create_quotation:data_type` [provisional] resource_usage/usage_create_quotation/data_type: data_quotation; evidence=ev_0017=obs_23[8:50]
- `claim:usage_send_quotation:crud` [provisional] resource_usage/usage_send_quotation/crud: unknown; evidence=ev_0018=obs_53[14:57]
- `claim:usage_send_quotation:system` [provisional] resource_usage/usage_send_quotation/system: system_email; evidence=ev_0018=obs_53[14:57]
- `claim:usage_send_quotation:data_type` [provisional] resource_usage/usage_send_quotation/data_type: data_quotation; evidence=ev_0018=obs_53[14:57]
- `claim:usage_approve_quotation:crud` [provisional] resource_usage/usage_approve_quotation/crud: unknown; evidence=ev_0019=obs_33[67:112]
- `claim:usage_approve_quotation:system` [provisional] resource_usage/usage_approve_quotation/system: dont_know; evidence=ev_0019=obs_33[67:112]
- `claim:usage_approve_quotation:data_type` [provisional] resource_usage/usage_approve_quotation/data_type: data_quotation; evidence=ev_0019=obs_33[67:112]
- `claim:usage_send_summary:crud` [provisional] resource_usage/usage_send_summary/crud: unknown; evidence=ev_0020=obs_33[214:254]
- `claim:usage_send_summary:system` [provisional] resource_usage/usage_send_summary/system: dont_know; evidence=ev_0020=obs_33[214:254]
- `claim:usage_send_summary:data_type` [provisional] resource_usage/usage_send_summary/data_type: data_month_end_summary; evidence=ev_0020=obs_33[214:254]

## Open questions

- `question:issue_month_end_path` [open] Is the month-end summary sent in addition to the amount-based path or instead of it? (target: step_send_month_end_summary, flow_create_month_end)

## Contradictions

- (none)

## Corrections

- (none)

## Completion

- status: `ended`
- termination reason: `existing replay records a normal protocol completion`
- unresolved: question:issue_month_end_path
- stakeholder confirmed: `False`
- content completeness: `incomplete`
