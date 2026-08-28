# business-interview-bench

Standalone migration target for the `business-interview` benchmark.

This repository is currently at **Phase 7**. It is an intentionally small
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
│   └── evaluation/     # graph-only and explicit-context evaluator facades
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
implemented without tau2. `evaluate_graph()` remains the graph-only API and
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
transcript or private sidecar. Phase 8 is the next migration boundary for
remaining runtime/integration concerns. See `migration/README.md` and
`migration/inventory.md` for details.
