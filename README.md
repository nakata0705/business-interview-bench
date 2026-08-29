# business-interview-bench

Standalone migration target for the `business-interview` benchmark.

This repository is currently at **Phase 11**. It is an intentionally small
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
│   ├── replay_data/    # packaged canonical seed9004 replay asset
│   ├── scenarios/      # tau2-free scenario/task catalog and Truth resources
│   └── stakeholders/   # private profile, knowledge, and address contracts
├── src/business_interview_bench/
│   └── inspect_adapter/ # Inspect task, solver, scorer, and replay Store
└── tests/
    ├── test_comparison_core.py
    ├── test_evaluation.py
    ├── test_interview_evaluation.py # observation/evidence/protocol checks
    ├── test_knowledge_coverage.py # coverage/primary parity checks
    ├── test_graph_contract.py
    ├── test_project_smoke.py
    ├── test_seed9004_fixture.py
    ├── test_stakeholder_projection.py # Truth-to-knowledge projection checks
    ├── test_inspect_adapter.py # deterministic Inspect replay/rescore checks
    ├── test_stakeholders.py # private runtime contract checks
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
parity. The canonical replay asset under
`src/business_interview/replay_data/seed9004/` contains the normalized Agent,
Truth, context, coverage, expected, and provenance payloads; tests and the
Inspect adapter share it rather than maintaining fixture copies.

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

## Phase 9: private stakeholder runtime input contract

The `business_interview.stakeholders` package defines the future simulator's
private inputs; the Phase 9 contract itself runs no projection or LLM:

```python
from business_interview.scenarios import get_scenario
from business_interview.stakeholders import StakeholderProfile

scenario = get_scenario("quotation_workflow_1")
profile = StakeholderProfile(stakeholder_id="sales", name="Sales")
# Phase 10 constructs the private graph from scenario.truth + profile.
```

`StakeholderProfile`/`StakeholderFilter` carries stable identity, Truth
visibility by business node/edge/property, independent per-concept
`description_known`/`terms_known` overrides with optional local terms, and
bounded `ForgettingConfig`. Phase 9 established this immutable input contract;
Phase 10 applies its forgetting policy and safe topology projection.

`StakeholderKnowledge` is separate from evaluator-only `KnowledgeCoverageView`.
It stores a stakeholder-local graph with value references, explicit known
absence (`None`), explicit `DONT_KNOW`, local concept descriptions/terms,
structural SOURCE/SINK and protected boundary edges, private local-to-Truth
mappings, and shortcut provenance. Local semantic addresses are resolved by
the pure `resolve_semantic_address()` API; invalid and unknown addresses are
rejected distinctly. These private mappings and local IDs are never part of
the public scenario prompt.

Phase 9 value models remain deeply immutable, not merely shallow-frozen:
sequences are stored as tuples and mapping fields use the standard library's
read-only `MappingProxyType`. Set-like inputs are canonicalized, while JSON
serialization still emits ordinary arrays/objects and accepts ordinary
list/dict input.

## Phase 10: Truth-to-stakeholder projection

Phase 10 completes the standalone domain pipeline from canonical Truth and an
immutable stakeholder profile to a private knowledge world, then to the
evaluator-only coverage view:

```python
from business_interview.stakeholders import (
    knowledge_coverage_view,
    project_knowledge,
)

knowledge = project_knowledge(truth, profile, seed=42)
coverage = knowledge_coverage_view(truth, knowledge)
```

`project_knowledge()` validates canonical Truth, applies element/property
visibility and three-valued slots, projects only referenced concepts, assigns
deterministic opaque local IDs, and records private Truth mappings. A supplied
seed uses a local `random.Random(seed)` stream without changing global random
state. `seed=None` uses a private `random.Random(None)` stream and is therefore
not reproducible when forgetting is enabled; exact projected knowledge should
be saved for replay and rescore.

Unsafe node-forgetting samples are rejected and retried up to
`ForgettingConfig.max_retries`. Safe serial contraction is limited to
non-structural nodes with exactly one unconditional predecessor and successor;
branch/merge/conditioned paths are rejected. SOURCE/SINK and protected
boundary structure remain present. `KnowledgeProjectionError` reports bounded
retry exhaustion rather than silently disabling forgetting.

`StakeholderKnowledge` is simulator-private world state and the source of
truth for knowledge coverage. `knowledge_coverage_view()` derives the
Truth-addressed `KnowledgeCoverageView` from that object; it is not a second
hand-maintained knowledge input. `StakeholderKnowledge` remains deeply
immutable and JSON-serializable.

## Phase 11: Inspect AI deterministic replay adapter

The execution boundary is deliberately one-way:

```text
Business Interview Core
        ↓
  Inspect Adapter
        ↓
deterministic replay
        ↓
    .eval log
        ↓
deterministic scorer
        ↓
offline inspect score
```

`inspect-ai` is a development/evaluation dependency only. Core packages
(`models`, `comparison`, `evaluation`, `scenarios`, `stakeholders`, and
`replay_data`) never import Inspect. The independent
`business_interview_bench.inspect_adapter` package is registered through
`[project.entry-points.inspect_ai]` under the stable namespace
`business_interview_bench`:

```bash
inspect eval business_interview_bench/seed9004_replay --model none
inspect score <log>.eval --scorer business_interview_bench/primary_scorer
```

The registered task has exactly one packaged seed9004 sample. Its custom
solver validates and stores canonical JSON payloads without calling
`generate()`, a model, or an external service. The typed
`BusinessInterviewReplayStore` records exact AgentGraph, canonical Truth,
InterviewEvaluationContext, KnowledgeCoverageView, expected oracle, and
provenance payloads. The scorer reconstructs those domain models from the
Store and delegates authoritative scoring only to `evaluate_primary()`;
`scenario` catalog reloads are not used for offline rescore. Truth/private
knowledge in an `.eval` log is an evaluator-private artifact by design.

The Inspect score preserves all 41 `PrimaryEvaluation` fields as named values;
it does not create a new weighted total. Primary reconstruction fields include
node/edge and semantic/concept metrics, fabricated counts, and
`reconstruction_pass`. Evidence/protocol diagnostics include evidence
coverage, provenance/observation counts, and protocol fields.
`knowledge_coverage` remains a context/informational field. The only Inspect
headline metric is the existing `reconstruction_pass` field.

A live `--model none` replay and `inspect score` offline rescore therefore use
the same exact logged inputs and produce byte-equivalent 41-field scores with
no model/API calls. Inspect owns execution, logging, and rescoring; the
existing evaluator remains deterministic domain code. Phase 12 is reserved for
stakeholder simulator semantics. LLM realization, response planning, Agent
runtime, Environment, InterviewDB, tools, and provider integration remain
unimplemented. See `migration/README.md` and `migration/inventory.md` for
migration details.
