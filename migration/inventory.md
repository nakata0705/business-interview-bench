# Migration source inventory and dependency boundary

## Snapshot

This inventory was recorded from the sibling checkout below without changing
it:

- repository: `/home/nakata0705/Projects/tau2-bench`
- remote: `https://github.com/nakata0705/tau2-bench.git`
- branch: `business-interview`
- HEAD: `00a98a5efbe9db2ccc3aaf2f04529ef50c323bb0`
- working tree: clean at capture time
- source scope: `src/tau2/domains/business_interview/`

The machine-readable copy of this provenance is
[`source.json`](source.json). The source checkout is an oracle, not a
submodule or runtime dependency of this project.

## Phase 2 implementation update

Phase 2 now implements only the standalone graph/domain model under
`src/business_interview/models/`:

- `concepts.py`: `ConceptKind`, `ConceptRef`, and `EvidenceRef`;
- `epistemic.py`: explicit Agent `UNSET`, `ABSENT`, and `DONT_KNOW` states;
- `graph.py`: `TruthConcept`/`TruthNode`/`TruthEdge`/`BusinessProcessGraph` and
  `AgentConcept`/`AgentNode`/`AgentEdge`/`AgentGraph`;
- `canonical.py`: canonical SOURCE/SINK validation, business node/edge and
  boundary helpers, and deterministic canonicalization.

The implementation uses only the standard library and Pydantic. No tau2
import exists under the new project's `src/` tree. JSON round-trip tests cover
both a canonicalized Truth graph and all four Agent slot states. Focused
oracle-derived tests cover the contract cases listed below; evaluator,
matching, stakeholder knowledge, simulator, runtime tools, and artifacts were
not migrated.

### Responsibilities intentionally omitted from source `graph.py`

The source `graph.py` also contains `InterviewDB` (a tau2 `DB` subclass),
`InterviewResult`, `Observation` storage, and runtime-oriented state helpers.
Phase 2 intentionally did not port those responsibilities. It also did not
port the source's generic `Node`/`Edge` naming, the full semantic-ID inventory,
or any evaluator-facing graph projection. The new model keeps only direct
Truth/Agent graph semantics, concept references, diagnostic evidence values,
and the canonical boundary contract.

## Current source shape

The tracked source directory currently contains the following domain modules
(the approximate line counts are useful for migration sizing):

| Module | Approx. size | Responsibility | Business Interview-specific? |
| --- | ---: | --- | --- |
| `graph.py` | 1,206 | Truth/Agent graph models, concept references, four-state Agent slots, stable semantic IDs, canonical SOURCE/SINK contract, observations, and `InterviewDB` | Yes; the graph primitives are the semantic core |
| `knowledge.py` | 958 | Three-state stakeholder world model, opaque stakeholder-local IDs, knowledge projection, bounded forgetting, and safe serial shortcut contraction | Yes |
| `facts.py` | 458 | Private sidecar annotations, semantic response-plan items, concept-alignment/terminology events, catalog validation, and `SemanticLedger` | Yes |
| `stakeholder.py` | 137 | `StakeholderFilter`, concept visibility overrides, and forgetting configuration | Yes |
| `scenario.py` | 631 | Quotation and lab Truth graphs, stakeholder views, local terminology, scenario lookup, and knowledge construction | Yes |
| `comparison.py` | 1,394 | Deterministic lexical concept matching, topology-aware node/edge alignment, slot scoring, precision/recall, and reconstruction metrics | Yes; its algorithms are reusable only behind the domain contract |
| `evaluation.py` | 498 | Primary Agent-to-Truth evaluator and result DTOs; also attaches diagnostics and reference-only stakeholder scores | Yes |
| `evaluation_diagnostics.py` | 707 | Per-concept/node/edge/slot failure diagnostics and canonical-boundary diagnostics | Yes; diagnostic-only |
| `reference_evaluation.py` | 447 | Reference-only `StakeholderKnowledge`-to-Truth comparison using private local-to-Truth mappings | Yes; never the primary Agent score |
| `artifact_provenance.py` | 564 | Canonical JSON serialization, fingerprints, seed provenance, input loading, and offline reference re-evaluation | Yes; migration/parity infrastructure |
| `tools.py` | 1,268 | Agent-facing glossary and graph mutation/read tools, evidence metadata, endpoints, validation, finish, and evaluation assertions | Domain API plus tau2 toolkit integration |
| `environment.py` | 271 | Conversation ledger integration, private sidecar binding, environment-owned observations, task loading, and episode completion | Runtime adapter |
| `user_simulator.py` | 878 | LLM stakeholder prompt, two-phase semantic plan/realization, JSON sidecar parsing, retries, and private metadata attachment | Runtime adapter; explicitly deferred |
| `utils.py` | 5 | Resolves policy/task data paths through tau2's `DATA_DIR` | Framework/data adapter |

`__init__.py` is empty. There are ignored compiled leftovers for names such
as `dag.py`, `ground_truth.py`, `data_model.py`, and `semantic.py`, but those
are not tracked source modules at this HEAD. The source README's historical
file table mentions `grounding.py`; the current source implementation instead
has the related helper at `scripts/business_interview_diagnostics/grounding.py`.
Neither observation is a reason to copy old files into the new project. The
older `artifacts/business_interview_real_llm/current_architecture_audit.json`
is also historical context from 2026-08-18 and names an earlier legacy
architecture; the source files at the recorded HEAD take precedence.

## Dependency boundary

The smallest useful boundary is a pure domain layer plus a thin runtime shell:

```text
pure domain models and semantics
  graph -> knowledge/stakeholder/facts -> scenario
  graph + comparison -> evaluation -> diagnostics/reference
  graph + knowledge -> artifact_provenance

runtime shell
  tools -> tau2 toolkit/task APIs
  environment -> tau2 environment/message/task APIs
  user_simulator -> tau2 user/message/LLM APIs
```

### Pure or nearly-pure layer

- `graph.py` uses the standard library and Pydantic. The only tau2 import is
  `tau2.environment.db.DB`, used by `InterviewDB`; Truth/Agent graph models,
  markers, canonical validation, and semantic-ID logic do not need tau2.
- `knowledge.py`, `facts.py`, `stakeholder.py`, `scenario.py`,
  `comparison.py`, `evaluation_diagnostics.py`, `reference_evaluation.py`,
  and `artifact_provenance.py` depend on Pydantic/standard library and on
  one another, not on the generic tau2 runtime. `knowledge.py` additionally
  uses `random` for bounded projection sampling.
- The primary evaluator is deterministic: `evaluate()` does not call an LLM,
  embedding service, web service, or database. Its `knowledge` argument is
  used for terminology/reference diagnostics; the scored target must be the
  explicit `truth` graph.
- In the new project, `InterviewDB` should not be copied as a tau2 DB subclass.
  A direct `InterviewState`/plain Pydantic state or an evaluator accepting
  `AgentGraph`, observations, and explicit `TruthGraph` is the intended seam.

### Framework shell

- `tools.py` imports `Task`, `ToolKitBase`, `ToolType`, and `is_tool` from
  tau2, in addition to domain models. Its public tool surface mutates an
  `InterviewDB` graph: concepts/mentions/terminology, nodes/edges, epistemic
  markers, endpoints, validation, and `finish_interview()`.
- `environment.py` imports tau2 `Message`/`UserMessage`, `Task`,
  `Environment`, and `load_file`. It owns the one-observation-per-accepted
  stakeholder-message rule and injects `[Observation obs_N]` into the
  Agent-visible copy while keeping raw text in the ledger.
- `user_simulator.py` imports tau2 message DTOs, `UserSimulator`, and
  `llm_utils.generate`, plus `loguru`. A wired stakeholder makes a private
  WHAT plan call followed by a HOW realization call; invalid plans/sidecars
  are retried. This is not needed for deterministic evaluator parity.
- `utils.py` ties policy/task paths to tau2's repository-wide `DATA_DIR`.
  `data/tau2/domains/business_interview/{policy.md,tasks.json,split_tasks.json}`
  are source assets, not Python dependencies.

### Implemented new-project boundary

1. Phase 2 keeps Pydantic as the only runtime dependency and exposes the graph
   API through `business_interview.models`.
2. `DB`, `Environment`, `ToolKitBase`, tau2 message classes, registry, CLI,
   and `UserSimulator` are absent from the core model.
3. No tau2 import or compatibility layer is used by the new `src/` tree.
4. LLM/API, voice, `loguru`, pandas, FastAPI, LiteLLM, evaluator, matching,
   and stakeholder-knowledge code remain outside Phase 2.

## Semantic contracts to preserve

- Truth is a complete `BusinessProcessGraph` with explicit protected
  structural SOURCE/SINK nodes and unconditional boundary edges. Structural
  elements are excluded from business score denominators.
- Agent state is a revisable `AgentGraph` with `UNSET`, known `ConceptRef`,
  explicit `ABSENT`, and explicit `DONT_KNOW` slot states. Evidence is
  diagnostic metadata, not a hidden correctness gate.
- Stakeholder knowledge is a masked three-state graph. Unknown values are
  `DONT_KNOW`; safe serial contraction may create a shortcut with recorded
  provenance, but branch/merge/conditioned unsafe contractions are rejected.
- Concept and graph correspondence is content/topology based and
  deterministic, not dependent on local Agent IDs. The matcher is lexical
  (normalized token/Dice overlap plus scenario terms), not semantic LLM
  understanding.
- The private sidecar and ledger are simulator/evaluator diagnostics. They
  must not leak stakeholder-local IDs, Truth mappings, or private knowledge to
  the Agent.

## Existing deterministic tests and source assets

Relevant source tests are located at:

- `tests/test_domains/test_business_interview/` — canonical graph contract,
  node/edge matching, diagnostics, graph behavior, and stakeholder Truth
  reference tests;
- `tests/test_business_interview_artifact_provenance.py` — canonical Truth /
  Knowledge serialization, fingerprints, seed metadata, and reference
  re-evaluation;
- `tests/test_business_interview_roundtrips.py` — offline environment/tool
  round trips, observation ownership, batching, and semantic-plan validation;
- `tests/experiments/business_interview/` plus
  `src/experiments/business_interview/` — usage/joint-alignment experiments,
  not primary evaluator dependencies.

The source data assets are:

- `data/tau2/domains/business_interview/policy.md`
- `data/tau2/domains/business_interview/tasks.json`
- `data/tau2/domains/business_interview/split_tasks.json`

The active scenario constructors in `scenario.py` are
`quotation_workflow_1` and `lab_sample_flow`; quotation sales/finance views
and Japanese local terms are scenario-specific inputs, not a generic
framework contract.

## Evaluator and parity inventory

### Primary evaluator entry point

The main entry point is:

```python
evaluate(
    db: InterviewDB,
    knowledge,
    spec: EvaluationSpec,
    stakeholder=None,
    *,
    truth,
    stakeholder_references=None,
) -> EvaluationResult
```

The effective inputs are the final `db.graph` (`AgentGraph`), an explicit
canonical `BusinessProcessGraph` Truth, optional `StakeholderKnowledge` for
local terminology/reference diagnostics, `EvaluationSpec` (currently an
empty/backward-compatible model), and optional named stakeholder reference
inputs. The lower-level deterministic seam is
`comparison.align_agent_to_truth()` followed by
`comparison.compare_aligned_graphs()`.

`EvaluationResult` exposes protocol/graph validity, node and edge
recall/precision, endpoint correctness, activity/actor/system/reads/writes/
rationale/condition correctness, concept recall/precision/correctness,
fabricated and unsupported counts, evidence/provenance diagnostics,
reconstruction/quality passes, and informational knowledge coverage.
`evaluation_diagnostics.py` adds alignment and slot reasons without changing
those score fields. `reference_evaluation.py` compares each stakeholder view
to Truth for diagnostics only and must not affect the primary Agent score.

### Determinism and saved inputs

- Primary graph evaluation and the reference evaluator are re-runnable with
  no LLM/API call when the final graph, observations (if evidence metrics are
  checked), explicit Truth, and exact stakeholder Knowledge are available.
- `artifact_provenance.py` defines the durable `evaluation_inputs` envelope:
  canonical TruthGraph, exact post-projection StakeholderKnowledge, stable
  stakeholder IDs, fingerprints, and seed provenance. The stored historical
  score is derived data; the envelope is the source of truth for re-evaluation.
- A complete conversational replay or a new stakeholder response still needs
  the simulator/LLM and is outside deterministic parity.
- Deterministically comparable fields should first be the component metrics,
  graph/concept alignments, slot states, endpoint semantics, fabricated /
  unsupported counts, `quality_pass`/`structural_pass`, and canonical contract
  diagnostics. Compare evidence/pass fields only when observations and the
  environment ledger are normalized identically.

### Candidate regression artifacts

The saved real-LLM directory is
`artifacts/business_interview_real_llm/` (159 files at capture time). The
following three seed pairs are the most useful first candidates, but they are
**legacy split artifacts**, not yet new-project fixtures:

| Seed | Files | Observed role | Caveat |
| ---: | --- | --- | --- |
| 9002 | `run_00_seed9002.json` + `.private.json` (+ `.diagnostics.json`) | Completed quotation interview; 32 Agent calls and 10 accepted observations; deliberately imperfect graph/evaluator result useful for ordinary scoring and evidence diagnostics | Legacy public Truth/Knowledge payloads omit the current canonical boundary metadata; no `evaluation_inputs` envelope |
| 9003 | `run_00_seed9003.json` + `.private.json` (+ `.diagnostics.json`) | `max_steps` truncation; 100 Agent calls and 9 accepted observations; useful for incomplete-protocol/termination behavior | Not a successful completion; same legacy input limitations |
| 9004 | `run_00_seed9004.json` + `.private.json` (+ `.diagnostics.json`) | Completed quotation interview; 34 Agent calls and 14 accepted observations; all six business nodes/edges and endpoints structurally reconstructed, but semantic quality remains incomplete | Best initial end-to-end parity candidate, but still a legacy split artifact |

`seed_9002_9003_9004_node_matching_comparison.json` is a matcher
regression/audit trace containing old-vs-current mappings and metric
changes; it is not a golden score. `seed_9002_9003_9004_provenance_comparison.json`
records that all three legacy Truth and Knowledge payloads are equal, that
legacy artifacts did not record stakeholder-generation/forgetting seeds, and
that their equal reference scores do not demonstrate independent forgetting
samples. `summary.json` is a small overview of the 9004 run.

The legacy artifacts have useful facts for diagnosis, including fingerprints
(`truth_graph`: `1f25228069fa6bc09b731765cdf1c1187e7ee54548740f1820a8fbbf2b418b30`;
`StakeholderKnowledge`:
`dab4110cb75861ffcaf883e8643d46f4aec0f09033183175a7889197515f4554`), but
should first be converted into an explicit, canonical parity fixture rather
than copied wholesale. The additional `data/simulations/**/results.json`
outputs and real-LLM private files are diagnostic material and should not be
mass-copied into this project.

## Phase 3 result: seed 9004 normalized fixture

Phase 3 uses exactly one case, the completed
`quotation_workflow_1` run with seed 9004. It has 34 Agent calls, 14 accepted
observations, six saved business nodes, six saved business edges, and both
business exits. It was selected over seed 9003 because 9003 stops at
`max_steps`, and over seed 9002 as the stronger completed first candidate.
No seed 9002/9003 fixture was added; Phase 4 comparison work is described
below.

The curated replay asset is:

```text
src/business_interview/replay_data/seed9004/
├── truth.json
├── agent.json
├── expected.json
└── provenance.json
```

`migration/scripts/build_seed9004_fixture.py` is the one-shot generator. It
reads only source files that exist, checks the source branch/HEAD/clean state
against `migration/source.json`, and uses the source checkout only as a
read-only generation dependency. It writes no raw artifact and has no runtime
import from tau2. The deterministic JSON portion is written with sorted object
keys; the only intentionally non-deterministic field is the provenance
`generation.generated_at` timestamp (a fixed `--generated-at` can be supplied
for a byte-identical rerun).

### Truth source and normalization

The source of Truth semantics is the legacy public artifact field
`truth_graph`, which is the saved deterministic data corresponding to
`src/tau2/domains/business_interview/scenario.py::quotation_truth()` at source
commit `00a98a5efbe9db2ccc3aaf2f04529ef50c323bb0`. The generator copies its
concept descriptions/terms, node slots, edge endpoints, and edge conditions
mechanically. It does not infer Truth from conversation text. The legacy
`start_node_id` and `end_node_ids` are passed as explicit entry/exit inputs to
the target `canonicalize_truth_graph()`, which adds only the protected
structural SOURCE/SINK nodes and boundary edges. `truth.json` therefore loads
as a `BusinessProcessGraph` and passes `validate_canonical_graph()`.

The legacy Truth payload omits the target's explicit boundary metadata and
contains serializer fields (`is_valid`, `validation_errors`, empty
`terminology_agreements`, and concept `display_label`/`mentions`) that are not
Truth semantics. Boundary metadata is deterministically generated; those
non-semantic fields are dropped.

### Agent source and normalization

`agent.json` comes directly from `run_00_seed9004.json:final_graph`, the
state saved at episode completion. It is not reconstructed from the natural
language transcript, tool-call sequence, or private annotation sidecar.
Legacy `Node`/`Edge` structures are mechanically mapped to the Phase 2
`AgentNode`/`AgentEdge` models; `start_node_id` becomes the one-element
`start_node_ids` list. Concept IDs, labels, confidence, evidence IDs/quotes,
endpoints, and list order are retained.

A significant legacy schema hazard is that empty source marker models do not
make `unset`, `absent`, and `dont_know` self-describing after permissive
Pydantic validation. The generator reads the raw marker keys explicitly and
emits target states `state=unset`, `state=absent`, and `state=dont_know`, so
none of the four Agent states are collapsed. The resulting `AgentGraph` is
validated and dump/reload semantic equality is tested.

### Expected oracle and discrepancy policy

`expected.json` is limited to the source evaluator's 41
`PrimaryEvaluationResult` fields for the primary Agent-to-Truth lane. The
source entry point is `tau2.domains.business_interview.evaluation.evaluate`.
The generator invokes it offline using the normalized Agent graph, source
`quotation_truth()`, and the legacy public observations/ledger plus private
knowledge object. This is source execution, not an evaluator port, and makes
no LLM/provider/network/simulator call.

The stored legacy field `run_00_seed9004.json:evaluator_metrics` was compared
field-by-field with the recomputation. All 41 fields matched exactly
(including `rationale_correctness=0.16666666666666666`), so the recomputed
fields are adopted and `legacy_stored_comparison.differences` is empty. The
private sidecar is used only during generation to supply the source evaluator's
exact knowledge input; its stakeholder-reference score is not copied. The
source diagnostics artifact is hashed and recorded in provenance but is not
used as an expected-metric source.

### Omitted data and public hygiene

The fixture intentionally omits the raw public/private artifacts, complete
conversation and message ledger, observation text, private annotation and
terminology ledgers, stakeholder knowledge graph/local IDs/Truth mappings,
tool/runtime state, reward/provider/LLM metrics, and diagnostic traces. The
final Agent's evidence IDs and quotes are retained because they are part of
its saved state; the expected evidence/protocol values remain a snapshot, not
a copied transcript. No API key, token, cookie, Authorization header, `.env`
content, credential, or provider secret is included.

`provenance.json` records the fixture schema/seed/task, source repository,
branch, exact source commit, artifact Git blob SHA-1 and SHA-256 values, source
oracle file hashes, generation method, field-level origins, omission reasons,
and generation timestamp. It also records hashes for the three deterministic
fixture files, while avoiding absolute paths as fixture contract data.

## Phase 4 result: deterministic comparison core

The comparison package is split into five small modules:

```text
src/business_interview/comparison/
├── __init__.py       # public API
├── projection.py     # immutable business-only Truth view
├── concepts.py       # lexical identity and concept assignment
├── assignment.py     # deterministic Hungarian assignment
├── alignment.py      # Node then business-Edge alignment
└── scoring.py        # aligned graph/content metrics and slot rules
```

The public entry points are `business_graph_projection()`,
`align_agent_to_truth()`, and `compare_aligned_graphs()`. The projection
validates canonical Truth, deep-copies business nodes/edges/concepts behind
read-only mappings, and retains boundary-derived business entry/exit IDs while
excluding structural SOURCE/SINK elements from all comparison denominators.

The implementation preserves the source identity/scoring boundary: concept
matching is NFKC/lowercase, stop/generic-token filtered lexical matching with
CJK bigrams, exact canonical-label priority, Dice similarity, per-kind
thresholded one-to-one assignment; Node matching requires asserted aligned
activity and uses actor/system/read/write/rationale reinforcement plus soft
WL-style topology; topology mismatch never rejects an activity candidate;
ambiguous equal optima stay unmatched; Edges are matched only after Nodes by
mapped endpoints and one-to-one condition-aware assignment. Truth absence is
scored only by Agent `ABSENT`, never by `UNSET` or `DONT_KNOW`, and lists use
source recall*precision plus unsupported-reference counting.

### Terminology extras audit

Using seed 9004's source final Agent state and source Truth, the audit compared
source alignment with the 21 terminology terms from stakeholder knowledge
against alignment with `{}`. Concept, Node, and Edge mappings and every Phase 4
metric were identical. No private knowledge was added to the target.

### Seed 9004 parity

`tests/test_comparison_core.py` loads only the checked-in Truth/Agent fixture;
it never imports or accesses the sibling source checkout. It compares these 23
fields exactly to `expected.json`: graph validity/creation, node and edge
precision/recall, start/end precision/recall, activity/actor/system/read/write/
rationale/condition correctness, concept correctness/recall/precision,
unsupported/fabricated counts, and glossary completeness. The parity result is
23 fields matched, zero differences, with no floating-point tolerance.

The Phase 3 snapshot's evidence coverage/authenticity, observation/protocol
fields, `knowledge_coverage`, reconstruction/quality facade, stakeholder
reference evaluation, diagnostics, and runtime/simulator fields remain
intentionally unimplemented. `expected.json` still contains the broader
Phase 3 oracle snapshot; Phase 4 consumes only the graph/content subset.

## Phase 5 result: minimal graph evaluator facade

Phase 5 implements the smallest evaluator seam that needs no runtime state:

```text
src/business_interview/evaluation/
├── __init__.py
├── evaluator.py
└── result.py
```

`business_interview.evaluation.evaluate_graph(agent, truth, *,
terminology_terms=None) -> GraphEvaluation` accepts only an `AgentGraph` and a
canonical `BusinessProcessGraph`/`TruthGraph`. It is pure and non-mutating. Its
implementation is orchestration and result assembly over the existing
projection, alignment, comparison, and completeness functions; it does not
reimplement scoring, concept matching, or node/edge matching. Explicit
`terminology_terms` are passed to the deterministic comparison matcher and do
not introduce a `StakeholderKnowledge` dependency.

`GraphEvaluation` contains exactly 26 fields: the 23 Phase 4 graph/content
fields plus `structural_pass`, `reconstruction_pass`, and `quality_pass`.
The source's current relationship is retained dynamically: one
`reconstruction_complete(comparison)` predicate supplies `structural_pass`,
and the other two pass fields alias that value. The predicate requires graph
creation/validity, all node and edge recall/precision, start/end correctness,
all activity/actor/system/read/write/rationale/condition scores, concept
recall/precision/correctness, and glossary completeness. It intentionally
does not add unsupported/fabricated counts because the source predicate does
not test them.

The 15 unavailable legacy fields are
`protocol_completed`, `protocol_pass`, `node_evidence_coverage`,
`ref_evidence_coverage`, `edge_evidence_coverage`,
`invalid_evidence_ref_count`, `ambiguous_evidence_ref_count`,
`marker_evidence_errors_surrogate`, `invalid_observation_reference_count`,
`authentic_observation_count`, `invalid_observation_source_count`,
`orphan_observation_count`, `provenance_authenticity_pass`, `evidence_pass`,
and `knowledge_coverage`. They are absent rather than dummy-valued because
they require a future explicit observation/message ledger, protocol state,
evidence/provenance rules, and stakeholder-knowledge mapping contract.
The legacy 41-field `PrimaryEvaluationResult` is therefore not copied.

Seed 9004 facade parity is exact at 26/26 using only the checked-in normalized
fixture files; tests do not import the source checkout. Correctness tests
cover perfect, invalid, incomplete, wrong-slot, concept, terminology, and
mutation cases. The source checkout, `migration/source.json`, and all Phase 3
fixture files remain migration inputs and are not modified. Phase 6 starts
with the separately specified observation/protocol input contract; no runtime,
evidence, knowledge, diagnostics, stakeholder-reference, tool, DB, simulator,
or tau2 compatibility work belongs to Phase 5.

## Phase 6 result: explicit context and 40-field interview evaluation

Phase 6 adds `ObservationRecord(id, text, turn)`, frozen `LedgerMessage(role,
content)`, and frozen `InterviewEvaluationContext(observations,
messages_by_turn, protocol_completed)` to the standalone model API. The
context is intentionally sparse and stores raw stakeholder text only; it does
not port `InterviewDB`, source-only observation metadata, the complete
conversation, or Agent-visible `[Observation obs_N]` markers.

`evaluate_graph()` remains the independent 26-field graph-only API.
`evaluate_interview(agent, truth, context, *, terminology_terms=None)` calls
that facade and assembles `InterviewEvaluation`, whose 40 fields are exactly
the legacy `PrimaryEvaluationResult` boundary excluding `knowledge_coverage`.
Graph pass fields remain the Phase 5 reconstruction predicate and are not
mixed with evidence or protocol pass values. `knowledge_coverage` is not
represented by a placeholder; it is the sole remaining primary field and the
Phase 7 boundary.

Evidence validation preserves source occurrence and counting behavior:
missing observation IDs are invalid references, quote spans must resolve, and
repeated references are counted at every validation visit. Node coverage uses
asserted-reference valid evidence or valid absence/unknown marker evidence;
reference coverage requires all evidence on an asserted reference; edge
coverage uses only edge-level evidence. Orphan tracking includes node refs,
node markers, edge refs, and value-bearing condition refs, exactly as the
source helper does. Source-defined `ambiguous_evidence_ref_count=0` and
`marker_evidence_errors_surrogate=0` are reproduced as documented constants.
Authenticity requires a user-role ledger message at the observation turn with
exact raw content equality. Protocol pass is exactly
`context.protocol_completed`, while graph reconstruction remains independent.

`migration/scripts/build_seed9004_evaluation_context.py` mechanically extracts
the 14 observations, their 14 required ledger messages, and
`interview_complete` from the persisted seed 9004 public artifact. The
checked-in `evaluation_context.json` is stable and contains no raw full
transcript. Phase 6 parity is exact 40/40 using only `truth.json`,
`agent.json`, `evaluation_context.json`, and `expected.json`; Phase 5 graph
parity remains 26/26. Focused tests cover span, provenance, marker, edge and
condition evidence, orphan, protocol, graph-pass isolation, and immutability.
Phase 7 is described below.

## Phase 7 result: coverage-only knowledge view and 41-field parity

Phase 7 adds `KnowledgeCoverageView` rather than the full
`StakeholderKnowledge` model. Its Truth-addressed maps contain only
`CoverageNode` (`truth_node_id`, scalar known/DONT_KNOW slots, and list
known-absent/DONT_KNOW/known-Truth-concept values) and `CoverageEdge`
(`truth_edge_id`, condition known/DONT_KNOW). Missing entries mean unknown
node/edge existence. Stakeholder-local IDs, mapping tables, descriptions,
terms, forgetting, shortcut provenance, and simulator-facing state remain
outside the contract.

`evaluate_knowledge_coverage()` follows source arithmetic exactly: Truth
business node/edge iteration only; node existence plus six slots plus expected
reads/writes elements; missing nodes still add list-element denominator
addresses; known-absent lists count all expected elements; known-values lists
use Truth concept IDs; DONT_KNOW counts nothing. Edge existence and condition
are separate addresses, and a known condition counts only when the edge exists.
Structural boundaries and extra knowledge entries do not affect the score.

`evaluate_primary()` reuses `evaluate_interview()` without recalculating its 40
fields and adds only informational `knowledge_coverage`. The explicit
`terminology_terms` path remains separate from the coverage view. The source
private knowledge artifact is read only by
`migration/scripts/build_seed9004_knowledge_coverage.py` during deterministic
fixture generation; the normalized fixture has no private metadata and
regenerates byte-identically.

Seed 9004 now has exact 41/41 primary parity, including
`knowledge_coverage=0.7166666666666667`, while 26/26 graph and 40/40 interview
parity remain green. Phase 7 completes primary evaluator migration. Phase 8
is described below.

## Phase 8 result: tau2-free scenario/task catalog

Phase 8 adds `src/business_interview/scenarios/`, a package-data-backed
catalog that answers only which interview scenario is selected. Its public
`ScenarioDefinition` contains `id`, `canonical_scenario_id`, `locale`,
canonical `truth`, public `prompt`, and ordered `initial_messages`.
`StakeholderPrompt` contains only `persona`, `reason_for_call`, and
`task_instructions`; `InitialMessage` contains only `role` and `content`.

The supported IDs are explicit and deterministic:

```text
quotation_workflow_1
quotation_workflow_1_ja
lab_sample_flow
```

`get_scenario()` performs exact ID lookup and raises `UnknownScenarioError`
for unknown IDs; it does not dynamically infer a scenario or translate a
suffix. `list_scenarios()` preserves catalog order. Both APIs return fresh
nested definitions rather than a mutable shared singleton. The package never
reads the source checkout or migration/test paths at runtime.

Quotation EN/JA definitions share one canonical Truth resource and differ only
in locale-specific public prompt/initial history. Truth concepts and canonical
terms remain unchanged for JA. The quotation Truth retains the source's
business IDs `r`, `cc`, `cq`, `ap`, `sq`, `me`, edges `e1`--`e6`, explicit
SOURCE/SINK, entry `r`, exits `sq`/`me`, and canonical text. It is semantically
equal to `src/business_interview/replay_data/seed9004/truth.json`. `lab_sample_flow` is loaded
from its own Truth resource and verifies that the catalog is not a
quotation-specific shortcut.

The catalog data extracts only the public persona, reason, task instructions,
and initial role/content history from source `tasks.json`. Tau2 Task wrappers,
`description.notes`, `evaluation_criteria.env_assertions`, `reward_basis`,
`env_type`, `func_name`, `known_info`, and `unknown_info` are intentionally
absent. Prompt metadata is not a business-fact source; canonical Truth stays
separate.

No `StakeholderFilter`, `StakeholderKnowledge`, `StakeholderKnowledgeGraph`,
Phase 7 `KnowledgeCoverageView` runtime state, local knowledge IDs, private
annotations, simulator, LLM, Agent runtime, Environment, InterviewDB, tools,
diagnostics, Inspect AI, or seed 9002/9003 expansion is included in Phase 8.
Phase 9 is described below.

## Phase 9 result: stakeholder profile and private world model

Phase 9 adds the standalone `business_interview.stakeholders` domain core.
`StakeholderProfile` (with `StakeholderFilter` as a descriptive alias) carries
stable `stakeholder_id`/`name`/`role`, visible business node and edge IDs,
per-node property visibility (`activity`, `actor`, `system`, `reads`,
`writes`, `rationale`), edge condition visibility, independent per-concept
description/terminology overrides, optional local terminology, and a bounded
`ForgettingConfig`. Probability bounds, positive `max_retries`, and the
safe-shortcut allow/deny flag are validated, but no stochastic behavior is
implemented.

`StakeholderKnowledge` is the future simulator's private semantic world model,
separate from Phase 7 `KnowledgeCoverageView`. Its local graph stores opaque
stakeholder-local node, edge, and concept IDs; value references; known absence
(`None`); explicit `DONT_KNOW`; local descriptions/terms; structural
SOURCE/SINK nodes and protected boundary edges; private local-to-Truth maps;
and shortcut edge/provenance metadata. The contract does not render these
private mappings into a public prompt and does not include the Truth graph as a
substitute for the local world model.

`resolve_semantic_address()` is a pure deterministic resolver for
`node:<local>`, node property/list-element, `edge:<local>`, edge condition, and
bare local concept addresses. Malformed syntax raises
`InvalidSemanticAddressError`; valid but missing objects raise
`UnknownSemanticAddressError`; `try_resolve_semantic_address()` returns
`None` for either case. No response plan, sidecar, annotation, or generated
speech layer is present.

All Phase 9 models are deeply immutable Pydantic value objects, not merely
shallow-frozen models. Sequences (`local_terms`, concept terms, reads/writes,
and shortcut metadata) are stored as tuples. Mapping fields use the standard
library's read-only `MappingProxyType`; JSON serialization still emits
ordinary objects/arrays and validation accepts ordinary list/dict input.
Profile and knowledge collection inputs are normalized so map/list insertion
order does not change semantics or serialized output. Focused tests directly
attempt mutations across top-level and nested collections. Existing Phase 1--9
tests and seed 9004 evaluator parity are unchanged.

## Phase 10 result: deterministic Truth-to-knowledge projection

Phase 10 adds `stakeholders/projection.py` and completes the standalone domain
pipeline:

```text
BusinessProcessGraph + StakeholderProfile + seed
    -> StakeholderKnowledge
    -> KnowledgeCoverageView
```

`project_knowledge()` validates canonical Truth up front, applies business
node/edge visibility and property visibility, preserves known value / known
absence / `DONT_KNOW`, applies independent concept description/terminology
overrides, and omits unreferenced concepts. It assigns deterministic,
index-only opaque local IDs (`skn_###`, `ske_###`, `skc_###`) and retains the
local-to-Truth mappings as private immutable metadata. Structural SOURCE/SINK
and protected boundary edges are always retained.

Node forgetting removes a business node only through safe serial contraction:
exactly one predecessor and successor, both unconditional, with no self-loop
or parallel endpoint relation. Branches, merges, conditioned paths, disabled
shortcuts, and any invalid post-forgetting topology reject the sample. Bounded
retries reuse one local RNG stream and raise `KnowledgeProjectionError` on
exhaustion; shortcut edge/provenance metadata retains all serial contractions.
`random.Random(seed)` never changes global random state. `seed=None` uses
private `random.Random(None)` and is intentionally non-reproducible when
forgetting is enabled, so exact projected knowledge should be persisted for
replay/rescore.

`knowledge_coverage_view(truth, knowledge)` validates and derives the
Truth-addressed evaluator-only `KnowledgeCoverageView` from the projected
private model. It is not independently authored state. The primary evaluator
still targets canonical Truth, and its existing contract is unchanged.

Focused `test_stakeholder_projection.py` covers deterministic IDs, local RNG,
retry behavior, safe/unsafe contraction, provenance, all slot semantics,
coverage derivation, deep immutability, and semantic-address resolution. LLM,
simulator loop, Agent runtime, Environment, InterviewDB, tools, diagnostics,
and provider configuration remain unimplemented; the Inspect adapter is added
in Phase 11 below.

## Phase 11 result: Inspect AI execution and offline rescore

Phase 11 introduces an independent Inspect adapter package while preserving the
core boundary:

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

`inspect-ai>=0.3.260` is a development dependency recorded in `uv.lock`; the
Pydantic-only core does not import it. `[project.entry-points.inspect_ai]`
registers `business_interview_bench.inspect_adapter._registry` under the
stable `business_interview_bench` namespace. Installed CLI names are
`business_interview_bench/seed9004_replay` and
`business_interview_bench/primary_scorer`.

The one-sample dataset reads the runtime-neutral canonical asset at
`src/business_interview/replay_data/seed9004/` and records only minimal sample
metadata: `replay_case_id`, `scenario_id`, and `source_commit_sha`. There is no
compatibility fixture or second payload copy. The expected oracle and
provenance stay in packaged migration/test data; they are not copied into the
runtime Store. The minimal solver validates the four scoring inputs and writes
only JSON-compatible dictionaries to the typed sample-scoped
`BusinessInterviewReplayStore`, then marks the state complete. It never calls
`generate()`, `get_model()`, an LLM, Agent simulation, or stakeholder
simulation. The Store contains only `agent`, `truth`, `evaluation_context`, and
`knowledge_coverage`.

The scorer restores those four Store dictionaries with `model_validate()` and
calls only the existing authoritative
`evaluate_primary(agent, truth, context, knowledge_coverage)`. It does not
reload the scenario catalog or any original fixture/source path during offline
rescore. Its dict-valued `Score.value` derives field names from
`dataclasses.fields(PrimaryEvaluation)` and preserves all 41 fields. Inspect's
standard `mean()` is selected for the `reconstruction_pass` dictionary key, so
that existing field is the headline without a custom metric or weighted
aggregate. Primary reconstruction includes node/edge and semantic/concept
metrics plus fabricated counts; evidence/protocol diagnostics include evidence
coverage and provenance/observation/protocol fields; `knowledge_coverage` is
context/informational.

The real CLI path is:

```bash
inspect eval business_interview_bench/seed9004_replay --model none
inspect score <generated-log>.eval \
  --scorer business_interview_bench/primary_scorer
```

Live replay and offline rescore both reproduce seed9004's 41/41 exact oracle
fields and equal score payloads with zero model/API calls, including with an
ambient model setting because `--model none` is explicit. Inspect owns
execution, logging, and rescoring; the evaluator remains deterministic core
domain code.

## Phase 12 result: one stakeholder response contract

Core response semantics live in `business_interview.stakeholders.response` and
`prompting`, with no Inspect or tau2 dependency. Immutable Pydantic models cover
`SemanticResponsePlan`, `PlannedResponseItem`, `SemanticAnnotation`,
`ConceptAlignmentAssertion`, `TerminologyConfirmation`, and
`StakeholderResponse`. `canonical_semantic_mode()` derives the one allowed mode
from `StakeholderKnowledge.resolve()`. Plan validation rejects unknown,
Truth-only, and mode-inconsistent IDs before realization. Sidecar validation
requires exact message quote/occurrence spans, complete plan coverage, no
unplanned business annotations, and concept-only alignment/terminology events.
Stakeholder-local handle and semantic-address leakage is rejected; Truth IDs
are not rejected because they are never rendered to the stakeholder. Prose is
never mined for facts.

`render_knowledge_prompt()` is a pure local-world renderer. It exposes only
visible positions, relations, concepts, stakeholder-local terms and opaque IDs,
with distinct known value, known absence, and DONT_KNOW states. It omits Truth
mappings, hidden facts, and external terminology.

`business_interview_bench.inspect_adapter.stakeholder` is deliberately thin:
it resolves only `get_model(role="stakeholder", required=True)`, performs the
plan and realization calls, parses with strict `model_validate_json()`, and
performs separate bounded semantic retries (default three per phase). It does
not use response schemas, custom providers, or the Phase 11 Store. MockLLM
integration covers exactly two successful role calls, invalid-plan and
invalid-realization retries, and explicit exhaustion errors.

## Phase 13 result: live multi-turn interview runtime

Phase 13 implements the first live Business Interview slice while keeping the
core independent of Inspect and tau2:

```text
Truth -> StakeholderKnowledge -> stakeholder WHAT/HOW -> public message
                                                        -> Observation
                                                        -> Candidate + tools
                                                        -> AgentGraph -> next question
                                                        -> explicit completion
                                                        -> evaluate_primary()

private SemanticLedger: validated annotations/alignments/terminology, bound to
exact public-message turns and observations, never placed in Agent messages.
```

`business_interview.runtime.LiveInterviewStore` is JSON-serializable state for
scenario ID, AgentGraph, raw public message ledger, observations, private
SemanticLedger, protocol state, and candidate/stakeholder turn counters. A
validated response is ingested atomically: only `StakeholderResponse.message`
becomes a public user message and the exact observation text/turn; the private
sidecar is retained separately and is never recovered by parsing prose.
Initial public stakeholder messages can be represented as empty semantic
entries, while generated responses always enter through the Phase 12 validator.

`business_interview.graph_mutations` owns pure add/update/remove node, edge,
and concept operations, node properties, edge conditions, explicit
ABSENT/DONT_KNOW, endpoints, and exact Observation EvidenceRefs. The thin
Inspect `@tool` wrappers only bind those operations to the live Store; mutation
receipts are compact and the full candidate-owned graph is returned only by
`get_agent_graph`. They expose no Truth, StakeholderKnowledge, or
SemanticLedger.

`multi_turn_interview_solver` uses Inspect's supplied default/current candidate
model and the existing required stakeholder role. Its explicit bounded loop
uses `candidate_turns` for interview turns and
`max_candidate_steps_per_turn` for candidate model generations (including the
question generation); it does not delegate runtime safety to
`Generate(tool_calls="loop")`. Every question invokes the stakeholder once at
the runtime level, then appends one validated public
response/observation before the next candidate turn. `complete_interview`
prevents later stakeholder calls and graph mutations. The public-only
`get_observations` tool exposes stable observation IDs/turns/text for exact
EvidenceRef attachment and no private ledger fields. Exhausting either hard
limit records an explicit incomplete protocol rather than completion.

The registered `phase13_interview` task accepts a scenario ID, plain
JSON/YAML `StakeholderProfile` mapping, projection seed, and bounded runtime
options. The programmatic `phase13_interview_task()` additionally accepts
exact `StakeholderKnowledge`. Live construction persists exact private setup
JSON for replay. Offline scoring validates that exact historical knowledge and
its coverage view without rerunning current projection code; profile/seed are
provenance metadata. Terminology confirmations retain exact interviewer
proposal and stakeholder-agreement provenance. `phase13_primary_scorer()`
provides the real Inspect path used by deterministic MockLLM integration tests;
final scoring delegates to the unchanged 41-field `evaluate_primary()`.

Phase 13 does not add real-provider E2E, calibration, model comparison,
LLM-as-judge, aggregate-score redesign, tau2 Environment/InterviewDB, or other
generic runtime infrastructure. These items remain Phase 14 work.
