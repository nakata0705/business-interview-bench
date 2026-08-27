# business-interview-bench

Standalone migration target for the `business-interview` benchmark.

This repository is currently at **Phase 2**. It is an intentionally small
Python 3.12 project managed with [`uv`](https://docs.astral.sh/uv/). The
existing `tau2-bench` checkout remains the migration oracle; this project does
not vendor tau2, copy the evaluator, or start an LLM simulator integration.

## Setup and checks

```bash
uv sync
uv run pytest
uv run ruff check .
uv run pyright
```

All checks are offline and do not require API keys.

## Layout

```text
business-interview-bench/
├── migration/
│   ├── README.md       # migration rules and parity plan
│   ├── inventory.md    # source/dependency inventory and Phase 2 result
│   └── source.json     # recorded source provenance
├── src/business_interview/
│   ├── __init__.py
│   └── models/         # tau2-free Truth/Agent graph model
└── tests/
    ├── test_graph_contract.py
    ├── test_project_smoke.py
    └── test_serialization.py
```

The graph model and canonical contract are now implemented without tau2.
Evaluator, simulator, CLI, and compatibility work remain deferred. See
`migration/inventory.md` before starting Phase 3.
