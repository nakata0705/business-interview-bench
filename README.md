# business-interview-bench

Standalone migration target for the `business-interview` benchmark.

This repository is currently at **Phase 8**. It is an intentionally small
Python 3.12 project managed with [`uv`](https://docs.astral.sh/uv/). The
existing `tau2-bench` checkout remains the migration oracle; this project does
not vendor tau2, copy the legacy evaluator, or start an LLM simulator
integration.

## Setup and checks

```bash
uv sync
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run pyright
```

All checks are offline and do not require API keys.

## Layout

```text
business-interview-bench/
├── migration/
│   ├── README.md       # migration rules and parity plan
│   ├── inventory.md    # source/dependency inventory and migration results
│   ├── scripts/         # read-only legacy-artifact migration tooling
│   └── source.json     # recorded source provenance
├── src/business_interview/
│   ├── __init__.py
│   ├── models/         # tau2-free Truth/Agent graph model
│   ├── comparison/     # tau2-free deterministic alignment/comparison core
│   ├── evaluation/     # graph-only and explicit-context evaluator facades
│   └── scenarios/      # tau2-free scenario/task catalog and Truth resources
└── tests/
    ├── fixtures/seed9004/ # normalized Truth/Agent/context/coverage/oracle
    ├── test_comparison_core.py
    ├── test_evaluation.py
    ├── test_interview_evaluation.py # observation/evidence/protocol checks
    ├── test_knowledge_coverage.py # coverage/primary parity checks
    ├── test_graph_contract.py
    ├── test_project_smoke.py
    ├── test_seed9004_fixture.py
    └── test_serialization.py
```

The graph model, seed 9004 normalized fixtures, deterministic
AgentGraph-to-TruthGraph comparison core, and the Phase 7 evaluator facades are
implemented without tau2. Phase 8 also provides a standalone scenario/task
catalog. `evaluate_graph()` remains the graph-only API and
returns exactly 26 graph/content and graph-pass fields. `evaluate_interview()`
adds the explicit raw observation/ledger/protocol contract and returns exactly
40 fields.

Phase 7 adds a separate minimal knowledge input and full primary facade:

```python
from business_interview.evaluation import evaluate_primary

result = evaluate_primary(
    agent_graph,
    canonical_truth_graph,
    context,
    knowledge_coverage_view,
)
```

`KnowledgeCoverageView` is Truth-addressed (`nodes_by_truth_id` and
`edges_by_truth_id`) and stores only known/DONT_KNOW scalar states, list
known-absent/DONT_KNOW/Truth-concept values, and edge condition knownness. It
is not the full `StakeholderKnowledge` model: no stakeholder-local IDs,
private mapping tables, descriptions, terms, forgetting, or shortcut
provenance are runtime inputs. `evaluate_primary()` reuses the 40-field
`evaluate_interview()` result and adds only `knowledge_coverage`, producing
exactly 41 fields. Coverage is informational and cannot change any pass value.

Seed 9004 now has exact 26/26 graph, 40/40 interview, and 41/41 primary
parity. The context and coverage fixtures retain only evaluator-required raw
inputs and Truth-addressed knowledge state; they do not copy a full
transcript or private sidecar.

## Phase 8: scenario/task catalog

The catalog API establishes the explicit scenario input contract without
requiring tau2:

```python
from business_interview.scenarios import get_scenario, list_scenarios

scenario = get_scenario("quotation_workflow_1")
scenario.truth
scenario.locale
scenario.prompt
scenario.initial_messages
```

The supported IDs are `quotation_workflow_1`,
`quotation_workflow_1_ja`, and `lab_sample_flow`. The English and Japanese
quotation records have different locale-specific public prompts and initial
messages but share one canonical semantic Truth resource. `lab_sample_flow`
is retained as a non-quotation scenario so the catalog remains a general
scenario contract rather than a quotation-only shortcut. Unknown IDs raise
`UnknownScenarioError`; catalog/list calls return fresh definitions in stable
order.

Scenario Truth resources, public prompt metadata, and initial message history
are separate package data. Task wrapper fields such as `description.notes`,
`env_assertions`, `reward_basis`, `env_type`, `func_name`, `known_info`, and
`unknown_info` are not runtime inputs. `ScenarioDefinition` is not
stakeholder simulator state: it contains no `StakeholderFilter`,
`StakeholderKnowledge`, local knowledge IDs, private annotations, LLM, DB,
Environment, or Agent runtime. A future simulator will receive public prompt
and Truth alongside separately constructed knowledge.

Phase 7 primary evaluator migration remains complete. Phase 9 is the next
boundary for the smallest separately defined stakeholder-simulator input
contract; simulator, knowledge projection, and LLM runtime are not started.
See `migration/README.md` and `migration/inventory.md` for migration details.
