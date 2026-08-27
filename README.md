# business-interview-bench

Standalone migration target for the `business-interview` benchmark.

This repository is currently at **Phase 3**. It is an intentionally small
Python 3.12 project managed with [`uv`](https://docs.astral.sh/uv/). The
existing `tau2-bench` checkout remains the migration oracle; this project does
not vendor tau2, copy the evaluator, or start an LLM simulator integration.

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
│   └── models/         # tau2-free Truth/Agent graph model
└── tests/
    ├── fixtures/seed9004/ # normalized Truth/Agent/oracle fixture
    ├── test_graph_contract.py
    ├── test_project_smoke.py
    ├── test_seed9004_fixture.py
    └── test_serialization.py
```

The graph model and one normalized seed 9004 parity fixture are implemented
without tau2. Evaluator, comparison, matching, simulator, CLI, and
compatibility work remain deferred. See `migration/inventory.md` before
starting Phase 4.
