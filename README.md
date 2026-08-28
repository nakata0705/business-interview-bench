# business-interview-bench

Standalone migration target for the `business-interview` benchmark.

This repository is currently at **Phase 6**. It is an intentionally small
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
    ├── fixtures/seed9004/ # normalized Truth/Agent/oracle fixture
    ├── test_comparison_core.py
    ├── test_evaluation.py
    ├── test_interview_evaluation.py # observation/evidence/protocol checks
    ├── test_graph_contract.py
    ├── test_project_smoke.py
    ├── test_seed9004_fixture.py
    └── test_serialization.py
```

The graph model, seed 9004 normalized fixtures, deterministic
AgentGraph-to-TruthGraph comparison core, and the Phase 6 evaluator facades are
implemented without tau2. The graph-only API remains:

```python
from business_interview.evaluation import evaluate_graph

result = evaluate_graph(agent_graph, canonical_truth_graph)
```

`evaluate_graph()` accepts only `AgentGraph + BusinessProcessGraph` and returns
`GraphEvaluation` with exactly 26 graph/content and graph-pass fields. The
Phase 6 API adds explicit raw observation/ledger/protocol input:

```python
from business_interview.evaluation import evaluate_interview

result = evaluate_interview(agent_graph, canonical_truth_graph, context)
```

`InterviewEvaluation` has exactly 40 fields: the graph result assembled from
`evaluate_graph()` plus evidence coverage, provenance, and protocol values.
It intentionally has no `knowledge_coverage`; that is the one remaining
legacy primary field and is the Phase 7 stakeholder-knowledge boundary. The
seed 9004 context stores only 14 raw observations, their authenticity-check
messages, and `interview_complete`, not a full transcript or Agent-visible
`[Observation ...]` markers. Its 40/40 parity and the existing graph 26/26
parity are exact. Stakeholder knowledge, diagnostics, simulator, CLI, and
compatibility work remain outside Phase 6. See `migration/README.md` and
`migration/inventory.md` for the migration boundary.
