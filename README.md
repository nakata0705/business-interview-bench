# business-interview-bench

Standalone migration target for the `business-interview` benchmark.

This repository is currently at **Phase 1**. It is an intentionally small
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
│   ├── inventory.md    # Phase 1 source/dependency inventory
│   └── source.json     # recorded source provenance
├── src/business_interview/
│   └── __init__.py     # package scaffold only
└── tests/
    └── test_project_smoke.py
```

The first implementation work belongs in a small, direct domain model and a
deterministic evaluator boundary. Compatibility with tau2 import paths,
class hierarchies, CLI commands, and generic framework abstractions is not a
goal. See `migration/inventory.md` before starting Phase 2.
