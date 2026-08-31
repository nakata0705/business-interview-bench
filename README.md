# business-interview-bench

Standalone migration target for the `business-interview` benchmark.

This repository is currently at **Phase 13**. It is an intentionally small
Python 3.12 project managed with [`uv`](https://docs.astral.sh/uv/). The
existing `tau2-bench` checkout remains the migration oracle; this project does
not vendor tau2, copy the legacy evaluator, or run real-provider benchmark
calibration.

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
│   ├── graph_mutations.py # pure AgentGraph mutation operations
│   ├── runtime.py       # live session/observation/semantic-ledger state
│   ├── comparison/     # tau2-free deterministic alignment/comparison core
│   ├── evaluation/     # graph-only and explicit-context evaluator facades
│   ├── replay_data/    # packaged canonical seed9004 replay asset
│   ├── scenarios/      # tau2-free scenario/task catalog and Truth resources
│   └── stakeholders/   # profile, knowledge, response, and prompt contracts
├── src/business_interview_bench/
│   └── inspect_adapter/ # Inspect tasks, solver, tools, scorers, and Stores
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
    ├── test_phase13_runtime.py # live state, ledger, and graph mutation checks
    ├── test_phase13_inspect.py # MockLLM multi-turn Inspect integration
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

The registered replay task has exactly one packaged seed9004 sample. A
separate registered `phase13_interview` task/factory is available for live
multi-turn runs; deterministic tests normally call it with MockLLM model
objects and a stakeholder model role. The replay task's minimal solver
validates the four canonical scoring inputs and stores only their JSON
payloads. It never calls `generate()`, a model, or an external service. The
`BusinessInterviewReplayStore` contains only `agent`, `truth`,
`evaluation_context`, and `knowledge_coverage`; expected oracle and provenance
remain packaged migration/test data, not runtime Store state. The scorer
reconstructs those four domain models with `model_validate()` and delegates
authoritative scoring only to `evaluate_primary()`; scenario catalog reloads
are not used for offline rescore.

The Inspect score preserves all 41 `PrimaryEvaluation` fields as named values;
it does not create a new weighted total. Inspect's standard `mean()` metric is
applied to the dict key `reconstruction_pass`, so that existing field remains
the headline without a custom metric implementation. Primary reconstruction
fields include node/edge and semantic/concept metrics, fabricated counts, and
`reconstruction_pass`; evidence/protocol diagnostics include evidence
coverage, provenance/observation counts, and protocol fields.
`knowledge_coverage` remains a context/informational field.

A live `--model none` replay and `inspect score` offline rescore therefore use
the same exact logged inputs and produce byte-equivalent 41-field scores with
no model/API calls. Inspect owns execution, logging, and rescoring; the
existing evaluator remains deterministic domain code.

## Phase 12: one stakeholder response contract

Phase 12 adds only the semantic contract for one stakeholder response. Core
code in `business_interview.stakeholders.response` defines immutable
`SemanticResponsePlan` and `StakeholderResponse` models, canonical mode
projection from the local resolver, strict JSON parsing, plan validation, and
sidecar validation. A plan can reference only stakeholder-local opaque IDs and
must use the mode implied by `StakeholderKnowledge`: `value`, `absent`,
`dont_know`, `exists`, or `mention`. Realized annotations must cover the
validated plan with exact message spans; alignments and terminology entries
must target local concepts. No facts are inferred from prose. Public-message
leakage protection rejects stakeholder-local handles and semantic addresses,
while Truth IDs remain valid
natural-language tokens because they are not shown to the stakeholder.

`render_knowledge_prompt()` is a pure core renderer. It emits only visible
positions, relations, concepts, local terms, and the distinct value/absence/
unknown states. Truth mappings, Truth IDs, hidden facts, and evaluator metadata
are never rendered, and canonical terminology is not supplemented externally.
A public response guard rejects stakeholder-local bare handles and semantic
addresses, but intentionally does not reject Truth IDs that were never shown
in the stakeholder prompt (for example a Truth node named `me`).

The thin Inspect-only `invoke_stakeholder_response()` adapter resolves
`get_model(role="stakeholder", required=True)` and performs two calls: WHAT
(plan JSON), deterministic plan validation, then HOW (response JSON),
deterministic sidecar validation. It uses strict `model_validate_json()`
parsing, no response-schema dependency, and separate bounded retry limits
(default three) for semantic output failures. Provider failures are not
silently converted into semantic retries. The adapter accepts ordinary
conversation and knowledge arguments and does not extend the Phase 11 Store.
MockLLM integration tests cover exactly two successful stakeholder-role calls,
plan/realization retries, and explicit retry exhaustion errors.

## Phase 13: live multi-turn interview runtime

Phase 13 adds the first complete multi-turn vertical slice. Core state remains
Inspect-free:

```text
Truth
  ↓
StakeholderKnowledge
  ↓
Stakeholder WHAT/HOW
  ↓
public message ──────────────────────┐
  ↓                                  │
Observation + raw public ledger     │
  ↓                                  │
Candidate Agent + graph tools        │
  ↓                                  │
AgentGraph ─────── next question ────┘
  ↓
explicit completion
  ↓
evaluate_primary()

private SemanticLedger
  └── validated annotations / concept alignments / terminology
      (bound to the exact public-message turn and Observation; never in
       Agent-visible messages)
```

`business_interview.runtime.LiveInterviewStore` is a JSON-serializable live
contract containing the scenario ID, AgentGraph, raw public messages,
observations, private SemanticLedger, protocol state, and turn counters.
`ingest_stakeholder_response()` validates the existing Phase 12 plan/response
contract before atomically appending the exact `StakeholderResponse.message`,
its `ObservationRecord`, and the private sidecar. No prose is re-parsed.

`business_interview.graph_mutations` provides pure add/update/remove node,
edge, and concept operations; slot value/ABSENT/DONT_KNOW operations; endpoint
updates; and exact Observation EvidenceRef attachment. Invalid IDs, references,
and terminal-state mutations raise explicit errors. Inspect `@tool` wrappers
only serialize the candidate-owned graph and delegate all semantics to these
operations.

`multi_turn_interview_solver` uses Inspect's supplied default/current candidate
model and the required `get_model(role="stakeholder", required=True)` role.
Each interview turn has an explicit `max_candidate_steps_per_turn` bound,
where one candidate step is exactly one candidate model generation, whether it
emits a tool call or a natural-language question. Inspect's unbounded tool loop
is not used. Each candidate question receives one validated stakeholder
response, and only its public text is appended to the candidate history. The
public-only `get_observations` tool exposes stable observation IDs/turns/text
when exact EvidenceRef attachment is needed; mutation receipts are compact and
`get_agent_graph` is the explicit full-graph read. `complete_interview` stops
further stakeholder calls and graph mutations. A hard interview-turn or
candidate-generation exhaustion is stored as `incomplete`, not as protocol
completion.

The registered `phase13_interview` task accepts a catalog `scenario_id`, a
plain JSON/YAML `stakeholder_profile` mapping, `stakeholder_seed`, and bounded
runtime options. It validates the mapping into the core `StakeholderProfile`
model, so a live task can be configured without putting a large exact
knowledge JSON object in CLI args:

```bash
inspect eval business_interview_bench/phase13_interview \\
  --task-config phase13-task.yaml --model <candidate-model> \\
  --model-role stakeholder=<stakeholder-model>
```

where `phase13-task.yaml` contains, for example:

```yaml
scenario_id: lab_sample_flow
stakeholder_seed: 17
stakeholder_profile:
  stakeholder_id: phase13-lab-tech
  name: Lab technician
  role: lab technician
  visible_node_ids: [n1, n2]
  visible_edge_ids: [l1]
  visible_node_attributes:
    n1: [activity, actor]
    n2: [activity, actor]
  visible_edge_attributes:
    l1: [condition]
```

Programmatic `phase13_interview_task()` additionally accepts exact
`StakeholderKnowledge`. Exact knowledge, profile, and seed are persisted in
evaluator-private Store JSON; the full-visibility
`phase13_smoke_interview_task()` helper is reserved for infrastructure tests.
Offline scoring treats the stored exact knowledge as authoritative and only
validates its model/structure and coverage consistency; it does not rerun the
current projection algorithm. Terminology confirmations retain exact
interviewer proposal and stakeholder-agreement provenance. Together with
`phase13_primary_scorer()`, this provides a real Inspect path for deterministic
MockLLM tests and connects the final state to the unchanged 41-field
`evaluate_primary()` evaluator.

Phase 13 intentionally does not add real-provider E2E, model comparison,
calibration, judge logic, or tau2 Environment/InterviewDB. Those remain Phase
14 work. See `migration/README.md` and `migration/inventory.md` for details.
