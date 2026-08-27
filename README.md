# business-interview-bench

Standalone migration target for the `business-interview` benchmark.

This repository is currently at **Phase 5**. It is an intentionally small
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
│   ├── inventory.md    # source/dependency inventory and Phase 3 result
│   ├── scripts/         # read-only legacy-artifact migration tooling
│   └── source.json     # recorded source provenance
├── src/business_interview/
│   ├── __init__.py
│   ├── models/         # tau2-free Truth/Agent graph model
│   ├── comparison/     # tau2-free deterministic alignment/comparison core
│   └── evaluation/     # pure AgentGraph + TruthGraph evaluator facade
└── tests/
    ├── fixtures/seed9004/ # normalized Truth/Agent/oracle fixture
    ├── test_comparison_core.py
    ├── test_evaluation.py
    ├── test_graph_contract.py
    ├── test_project_smoke.py
    ├── test_seed9004_fixture.py
    └── test_serialization.py
```

The graph model, seed 9004 normalized fixture, deterministic
AgentGraph-to-TruthGraph comparison core, and the Phase 5 evaluator facade are
implemented without tau2. The public evaluator is:

```python
from business_interview.evaluation import evaluate_graph

result = evaluate_graph(agent_graph, canonical_truth_graph)
```

It is a pure function of `AgentGraph + BusinessProcessGraph` and returns
`GraphEvaluation` with exactly 26 fields: the 23 Phase 4 graph/content metrics
plus `structural_pass`, `reconstruction_pass`, and `quality_pass`. These are
the only values computable without observations, protocol state, or
stakeholder knowledge, so the legacy 41-field `PrimaryEvaluationResult` was
not copied and unavailable values are not filled with placeholders. The
checked-in seed 9004 fixture has exact 26/26 parity. Evidence/protocol,
stakeholder knowledge, diagnostics, simulator, CLI, and compatibility work
remain outside this phase. See `migration/README.md` and
`migration/inventory.md` for the migration boundary.
