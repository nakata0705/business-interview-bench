# Migration notes

## Phase 1–4 contract

- `tau2-bench` on the `business-interview` branch is the **migration oracle**.
- The source repository and `migration/source.json` are read-only migration
  inputs. Do not change source code or discard pre-existing working-tree
  changes.
- The new project does not need tau2's internal structure, compatibility
  imports, class hierarchy, CLI, or generic framework abstractions.
- What must be preserved is the meaning of a Business Interview and its
  evaluation results, not tau2 implementation details.
- A normalized fixture is a deterministic parity input/snapshot, not a reason
  to call a real LLM or to copy a raw public/private artifact.

## Phase 2 status

The tau2-free Truth/Agent graph model is implemented in
`src/business_interview/models/`. It includes explicit Agent epistemic states,
canonical SOURCE/SINK validation, deterministic canonicalization, and JSON
round-trip coverage. Evaluator, stakeholder knowledge, simulator, and runtime
integration remain deferred.

## Phase 3 status: seed 9004 normalized parity fixture

Phase 3 is complete for one replay asset only:
`src/business_interview/replay_data/seed9004/`. The generation tool is
`migration/scripts/build_seed9004_fixture.py`; it requires the sibling source
checkout only while generating and never adds tau2 to the target runtime.

### Why seed 9004

Seed 9004 is the strongest first parity candidate: it is a completed
`quotation_workflow_1` episode with all six business nodes, all six business
edges, both declared business exits, and 14 accepted observations. Seed 9003
is intentionally incomplete and seed 9002 is a less complete candidate; neither
is part of Phase 3.

### Truth restoration

`truth.json` is built from the legacy public artifact's deterministic
`truth_graph` field, which is equivalent to the source oracle constructor
`scenario.py::quotation_truth()`. It is not inferred from natural-language
transcript text. Legacy concept/node/edge semantics are normalized into the
Phase 2 Pydantic models, then the legacy `start_node_id`/`end_node_ids` are
passed to `canonicalize_truth_graph()` to add only the protected explicit
SOURCE/SINK boundary nodes and unconditional boundary edges. The resulting
Truth validates with `validate_canonical_graph()` and has deterministic
mapping serialization.

The legacy Truth payload's main deficiency is that its serializer omitted the
canonical boundary metadata and retained Agent-oriented endpoint/diagnostic
fields. Those fields are either deterministically reconstructed (boundaries)
or intentionally dropped (serializer-only metadata).

### AgentGraph restoration

`agent.json` is built directly from the saved episode-final
`public.final_graph`, never by replaying or reinterpreting the transcript.
Legacy `Node`/`Edge` names and the single `start_node_id` are mechanically
mapped to `AgentNode`/`AgentEdge` and `start_node_ids`. References, confidence,
evidence quotes, endpoints, and all four epistemic states are retained. In
particular, legacy `unset`, `absent`, and `dont_know` marker objects are read
by their explicit serialized marker and are not collapsed by a permissive
legacy Pydantic union.

The legacy split artifact has no durable `evaluation_inputs` envelope and its
private sidecar contains evaluator-private annotations and stakeholder-local
Truth mappings. Those data are read only when the generator runs the oracle;
they are not copied into the public fixture.

### Expected oracle fields

`expected.json` contains only the source evaluator's deterministic
`PrimaryEvaluationResult` fields for the primary Agent-to-Truth lane (41
fields), plus an explicit stored-versus-recomputed comparison. The generator
runs `tau2.domains.business_interview.evaluation.evaluate` offline with the
saved final graph, source `quotation_truth()`, public observations/ledger, and
the private knowledge object. It does not call an LLM, provider, network, or
simulator. The legacy `evaluator_metrics` values and the recomputed values
matched for all 41 fields, so the recomputed snapshot is adopted and
`differences` is empty.

Stakeholder-reference scores, detailed diagnostics, joint audits, and runtime
or provider metrics are not mixed into `expected.json`. The source diagnostics
artifact is recorded in provenance only.

### Intentionally omitted data

The fixture does not copy the raw public artifact, raw private sidecar,
conversation/db message ledger, observation text, private annotation ledgers,
stakeholder knowledge graph, tool/runtime state, LLM/provider metrics, reward
metadata, or diagnostics traces. Evidence IDs and quotes needed to describe
the final Agent state remain in `agent.json`; evidence/pass values in the
oracle snapshot are not a transcript substitute. No credentials, API keys,
authentication material, or provider secrets are present in the normalized
files.

## Phase 4 status: deterministic comparison core

Phase 4 adds only the tau2-free comparison package under
`src/business_interview/comparison/`. Its public API is:

```python
from business_interview.comparison import (
    align_agent_to_truth,
    business_graph_projection,
    compare_aligned_graphs,
)
```

`business_graph_projection()` creates a pure business-only view of canonical
Truth. Structural SOURCE/SINK nodes and protected boundary edges are removed
from concepts, topology, endpoint checks, alignment, and every scoring
denominator. The input Truth is never mutated.

The core retains source deterministic semantics: NFKC/lowercase lexical
normalization, Latin token and CJK bigram signatures, stop/generic-token
filtering, exact canonical-label matching, Dice similarity, per-kind
thresholded one-to-one assignment, activity-gated Node alignment with
reinforcement attributes and soft WL-style topology, conservative ambiguous
optima, endpoint-first one-to-one Edge alignment, and source four-state slot
scoring. Truth absence is correct only for Agent `ABSENT`; `UNSET` and
`DONT_KNOW` are not absence answers.

### Terminology extras audit

On seed 9004, the source alignment was run with the 21 saved stakeholder
terminology terms and again with `{}`. Concept mapping, Node mapping, Edge
mapping, and all Phase 4 comparison metrics were identical. The target
therefore does not reintroduce private stakeholder knowledge or infer
terminology extras.

### Seed 9004 parity boundary

`tests/test_comparison_core.py` loads only the checked-in `truth.json` and
`agent.json`, runs the target comparison, and compares exact values with
`expected.json`. The 23 parity fields are:

- graph/node/edge counts and precision/recall;
- start/end correctness;
- activity, actor, system, read, write, rationale, and condition correctness;
- concept correctness/recall/precision;
- unsupported and fabricated counts; and glossary completeness.

All 23 fields match the source oracle exactly. No tolerance is used.
Correctness tests also cover lexical generic-token behavior, CJK/NFKC,
one-to-one assignment, local-ID renaming, insertion order, symmetric Node
ambiguity, topology mismatch, parallel Edges, epistemic states, and
unsupported list references.

The following source evaluator fields remain intentionally unported at the
Phase 4 boundary: evidence coverage/authenticity, observation and protocol
fields, `knowledge_coverage`, stakeholder reference evaluation, diagnostics,
and all simulator/runtime integration. The 41-field Phase 3 snapshot remains
an oracle artifact; Phase 4 implements only its graph/content subset.

## Phase 5 status: graph evaluation facade

Phase 5 adds a small tau2-free evaluation package around the Phase 4 core:

```text
src/business_interview/evaluation/
├── __init__.py
├── evaluator.py  # orchestration and result assembly only
└── result.py     # frozen GraphEvaluation value object
```

The public API is:

```python
from business_interview.evaluation import evaluate_graph

result = evaluate_graph(
    agent_graph,
    canonical_truth_graph,
    terminology_terms={"truth_concept_id": ["explicit extra term"]},
)
```

`evaluate_graph()` is a pure function of `AgentGraph` and canonical
`BusinessProcessGraph` (`TruthGraph`). It performs only
`business_graph_projection()` → `align_agent_to_truth()` →
`compare_aligned_graphs()` → reconstruction completeness → result assembly.
The projection protects the SOURCE/SINK denominator boundary, and neither
input graph is mutated. `terminology_terms` is an optional deterministic
pass-through to the existing comparison matcher; no `StakeholderKnowledge`
object is accepted.

`GraphEvaluation` has exactly 26 fields: the 23 Phase 4 graph/content metrics
plus `structural_pass`, `reconstruction_pass`, and `quality_pass`. The source
predicate is preserved exactly: all three current pass values share
`reconstruction_complete(comparison)`, which requires graph creation and
validity, node/edge recall and precision, start/end correctness, every
activity/actor/system/read/write/rationale/condition score, concept
recall/precision/correctness, and `glossary_complete`. Unsupported and
fabricated counts are reported but are not independently added to that
predicate because the source predicate does not include them.

The legacy `PrimaryEvaluationResult` has 41 fields. It was not copied: the
other 15 values require inputs that a pure Agent/Truth graph function does not
have, and no unavailable value is represented by `0`, `False`, `None`, or a
dummy field. The intentionally unavailable fields are:

- `protocol_completed`, `protocol_pass`;
- `node_evidence_coverage`, `ref_evidence_coverage`,
  `edge_evidence_coverage`;
- `invalid_evidence_ref_count`, `ambiguous_evidence_ref_count`,
  `marker_evidence_errors_surrogate`;
- `invalid_observation_reference_count`, `authentic_observation_count`,
  `invalid_observation_source_count`, `orphan_observation_count`;
- `provenance_authenticity_pass`, `evidence_pass`, `knowledge_coverage`.

Those fields must wait for a separately designed Phase 6 input contract: an
explicit observation/message ledger and protocol-completion state for the
observation/evidence/provenance lanes, plus an explicit stakeholder-knowledge
contract for knowledge coverage. That contract is not inferred from graph
slots and is not part of Phase 5.

`tests/test_evaluation.py` compares the facade against only the checked-in
seed 9004 `truth.json`, `agent.json`, and `expected.json`; the source checkout
is not imported at test runtime. All 26 fields match the oracle exactly
(26/26). Additional tests cover perfect graphs, invalid graphs, missing nodes,
wrong slot values, incomplete concept precision/recall, input immutability,
and deterministic terminology pass-through.

## Phase 6 result: explicit observation/provenance/protocol contract

Phase 6 adds a deliberately small tau2-free context model:

```text
ObservationRecord       id, raw text, source message turn
LedgerMessage           role, raw content
InterviewEvaluationContext
                        observations, sparse messages_by_turn, protocol_completed
```

`ObservationRecord` and `LedgerMessage` are frozen value models. The context
contains only evaluator-required raw stakeholder text and the corresponding
role/content ledger entries; it does not contain `source_id`, observation
order/locale, a tau2 `InterviewDB`, runtime state, or the Agent-visible
`[Observation obs_N]` marker. `messages_by_turn` may be sparse because source
authenticity only indexes the message at each observation's `turn`. A full raw
transcript is not persisted: the evaluator needs only those observation texts
and turn-indexed messages, while copying the rest would expand the public
artifact surface without adding evaluator semantics.

The new public API is:

```python
from business_interview.evaluation import evaluate_interview

result = evaluate_interview(agent, truth, context, terminology_terms=None)
```

`evaluate_graph(agent, truth)` remains the graph-only 26-field API. The new
`InterviewEvaluation` is assembled from that result and adds the source
observation/evidence/protocol lanes; it has exactly 40 fields and deliberately
has no `knowledge_coverage`. Thus the Phase 6 boundary is 40/40 of the legacy
41-field `PrimaryEvaluationResult`; `knowledge_coverage` is the sole remaining
primary field and is reserved for Phase 7.

### Evidence and provenance semantics

The evaluator preserves the source evaluator's current rules rather than
turning evidence into a graph-validity gate. A missing observation ID is an
invalid evidence reference and a quoted reference is valid only when
`EvidenceRef.resolve_span()` finds the requested occurrence. Every validation
visit counts: identical EvidenceRefs are not deduplicated. Node coverage is a
node hit when an asserted ConceptRef has any valid evidence or an
`ABSENT`/`DONT_KNOW` marker has valid evidence. Asserted-reference coverage
requires non-empty evidence with every evidence item valid. Edge coverage uses
only `AgentEdge.evidence`; condition evidence is not added to that denominator.

Orphan tracking follows `_referenced_observations()`'s source surface: node
reference evidence, node absence/unknown marker evidence, edge evidence, and
value-bearing edge-condition evidence are included. Condition marker evidence
is not added because it is not included by the source function. The source
result currently defines `ambiguous_evidence_ref_count` and
`marker_evidence_errors_surrogate` as literal zero fields; they are reproduced
as source-contract constants, not unknown/dummy values. `evidence_pass` is
provenance authenticity plus all three coverage values equal to 1.0.

For each observation, provenance requires a ledger entry at its turn with
`role == "user"` and exact equality between raw ledger content and raw
observation text. This yields authentic/invalid-source counts and the source
orphan count. `protocol_completed` is copied from the context and
`protocol_pass` is exactly the same boolean. `structural_pass`,
`reconstruction_pass`, and `quality_pass` remain the Phase 5 graph predicate;
evidence/protocol failures never alter graph reconstruction.

### Seed 9004 context normalization and parity

`migration/scripts/build_seed9004_evaluation_context.py` mechanically extracts
only `observations`, `db_messages_ledger[observation.turn]`, and
`interview_complete` from the persisted seed 9004 public artifact. It checks
the source branch/HEAD/clean state against `migration/source.json`, writes
stable JSON, and changes neither the source checkout nor the four Phase 3
fixture files. The script does not reinterpret transcript language and never
copies the raw public/private artifact. The checked-in context has 14
observations and 14 sparse authenticity messages; its text is raw stakeholder
text with no markers.

`tests/test_interview_evaluation.py` compares only
`truth.json`, `agent.json`, `evaluation_context.json`, and `expected.json` at
runtime. It selects the 40 non-knowledge fields from the existing source oracle
and requires exact 40/40 equality; the existing graph-only test continues to
require exact 26/26. The source checkout is not needed for pytest.

Focused tests cover valid spans, unknown IDs, invalid quotes and occurrences,
role/text/missing-turn provenance failures, orphan observations, marker and
edge coverage, condition-evidence orphan tracking, false protocol completion,
independence of graph reconstruction from evidence, and input immutability.
No StakeholderKnowledge, terminology extraction from private knowledge,
stakeholder reference evaluator, diagnostics, tools, DB, simulator, LLM,
Inspect AI, seed 9002/9003, or legacy compatibility result is implemented in
Phase 6. Phase 7 is described below.

## Phase 7 result: minimal knowledge coverage and complete primary parity

Phase 7 ports only the input surface actually read by source
`comparison.py::knowledge_coverage()`. `KnowledgeCoverageView` is a
Truth-addressed, read-only evaluator view with:

```text
KnowledgeCoverageView
  nodes_by_truth_id: dict[str, CoverageNode]
  edges_by_truth_id: dict[str, CoverageEdge]

CoverageNode
  truth_node_id, activity, actor, system, reads, writes, rationale

CoverageEdge
  truth_edge_id, condition
```

Scalar slots are only `known` or `dont_know`, because source coverage does not
inspect scalar concept identity. List slots use `CoverageListSlot` with
`known_absent`, `dont_know`, or `known_values` containing Truth concept IDs.
Missing node/edge entries mean unknown existence. This is intentionally not a
copy of `StakeholderKnowledge`: there are no `skn_*`/`ske_*`/`skc_*` IDs,
local-to-Truth mapping tables, descriptions, terminology, annotations,
forgetting configuration, or shortcut provenance in the runtime contract.
The Truth-addressed form is selected because coverage needs mapping results,
not the stakeholder projection machinery that produced them.

`evaluate_knowledge_coverage(truth, knowledge)` is an independent pure
function. It iterates only `business_node_ids(truth)` and
`business_edge_ids(truth)`, so SOURCE/SINK and boundary elements never enter
the denominator. For every Truth node it counts node existence, six property
slots, and one address for every expected reads/writes element. A missing node
still contributes those reads/writes element addresses. A known-absent list
(source `None`) counts the slot and every expected element as known; a
known-values list counts only mapped Truth concept IDs; `dont_know` counts
neither the slot nor its elements. Every present node scalar except
`dont_know` is known. For every Truth edge it counts existence and condition
separately; a present edge with a known condition counts both, while a
`dont_know` condition counts only existence. Condition identity is not used.
Extra knowledge entries are ignored by Truth iteration.

The `terminology_terms` input remains separate and explicit. It is passed only
to the deterministic Agent/Truth comparison matcher through
`evaluate_interview()`; `KnowledgeCoverageView` contains no terms or private
knowledge description. The seed 9004 terminology audit remains unchanged.

`evaluate_primary(agent, truth, context, knowledge)` reuses the complete
`evaluate_interview()` 40-field result and adds only the computed
`knowledge_coverage` field. `PrimaryEvaluation` therefore has exactly 41
fields. Coverage is informational and does not affect structural,
reconstruction, quality, evidence, or protocol passes.

`migration/scripts/build_seed9004_knowledge_coverage.py` loads the persisted
source private knowledge object only during generation, resolves its local
node/edge/concept references to Truth IDs, filters to business Truth
addresses, and writes only the normalized coverage states. The checked-in
`knowledge_coverage.json` contains no private sidecar content and regenerates
byte-identically.

`tests/test_knowledge_coverage.py` covers node/edge existence, scalar and list
states, source's missing-node list denominator, known-absent special case,
condition knownness, structural exclusion, extra entries, input immutability,
and isolation of all other 40 fields. Using only the five checked-in inputs
`truth.json`, `agent.json`, `evaluation_context.json`,
`knowledge_coverage.json`, and `expected.json`, seed 9004 achieves exact
primary parity 41/41 (including `knowledge_coverage =
0.7166666666666667`); graph and interview parity remain 26/26 and 40/40.

Primary evaluator migration is complete at Phase 7. Phase 8 is described
below.

## Phase 8 result: standalone scenario/task catalog

Phase 8 establishes the runtime input contract for selecting an interview
without importing tau2. The public models are:

```text
ScenarioDefinition
  id, canonical_scenario_id, locale, truth, prompt, initial_messages

StakeholderPrompt
  persona, reason_for_call, task_instructions

InitialMessage
  role, content
```

`ScenarioDefinition` intentionally stops at scenario identity, locale,
canonical Truth, public stakeholder/task prompt metadata, and ordered initial
conversation messages. It is not stakeholder simulator state. In particular,
it does not contain `StakeholderFilter`, `StakeholderKnowledge`, a
`StakeholderKnowledgeGraph`, local knowledge IDs, mapping tables, private
annotations, forgetting/masking, or LLM/runtime state. Phase 7's
`KnowledgeCoverageView` is evaluator-only and is not used as scenario runtime
knowledge.

The explicit catalog contains exactly these IDs, in deterministic order:

```text
quotation_workflow_1
quotation_workflow_1_ja
lab_sample_flow
```

`get_scenario(id)` accepts only those concrete IDs and raises
`UnknownScenarioError` for anything else; it does not infer or transform a
locale from a suffix. `list_scenarios()` and `get_scenario()` create fresh
nested definitions, so callers do not receive a mutable shared singleton.

Truth resources and task metadata are separate package data under
`src/business_interview/scenarios/data/`. The quotation English and Japanese
records point to the same canonical quotation Truth while carrying different
`locale`, public prompt text, and initial message history. The canonical Truth
is not translated for Japanese: Japanese vocabulary remains a future
stakeholder-realization concern. `lab_sample_flow` is included to demonstrate
that the catalog contract is not a quotation-specific special case; its lab
Truth and prompt have no quotation data.

The catalog's Truth resources validate with the standalone
`validate_canonical_graph()` contract. Quotation retains the source's six
business nodes (`r`, `cc`, `cq`, `ap`, `sq`, `me`), six business edges
(`e1`--`e6`), explicit protected SOURCE/SINK boundaries, entry `r`, exits
`sq`/`me`, and 22 non-rationale Truth concepts plus the source rationale
concept. (The graph model therefore has 23 `TruthConcept` records in total.)
Its catalog Truth is semantically
equal to the Phase 3 `truth.json`; lab Truth is migrated independently from
source `lab_sample_flow`.

Only `persona`, `reason_for_call`, `task_instructions`, and ordered role/content
initial messages are extracted from `tasks.json`. Tau2 task wrappers and
non-runtime fields (`description.notes`, `evaluation_criteria.env_assertions`,
`reward_basis`, `env_type`, `func_name`, `known_info`, and `unknown_info`) are
not copied. Prompt text is data, not a second Truth source; Truth remains the
canonical business-fact source.

The public API is:

```python
from business_interview.scenarios import get_scenario

scenario = get_scenario("quotation_workflow_1")
scenario.truth
scenario.locale
scenario.prompt
scenario.initial_messages
```

`tests/test_scenario_catalog.py` verifies catalog IDs/order, unknown-ID
behavior, canonical validation, quotation fixture equality and boundaries,
EN/JA Truth sharing and prompt/message differences, lab isolation, fresh
objects, omitted task-wrapper/private fields, and direct connection from
catalog Truth into the existing 41-field evaluator. Normal pytest does not
read the source checkout or replay assets as runtime catalog data beyond the
canonical packaged asset.

Phase 8 established the public scenario input contract. Phase 9 then defined
its separately constructed stakeholder profile/private knowledge boundary;
Phase 10 applies that boundary as a pure Truth-to-knowledge projection. The
simulator, LLM API, Agent runtime, Environment, InterviewDB, tools,
diagnostics, and Inspect AI integration remain outside these domain layers.

## Phase 9 result: private stakeholder runtime input contract

Phase 9 adds `src/business_interview/stakeholders/` without adding a runtime
loop. The public configuration contract is `StakeholderProfile` (also exposed
as the source-shaped `StakeholderFilter` alias):

```text
stakeholder_id, name, role
visible_node_ids, visible_edge_ids
visible_node_attributes: activity/actor/system/reads/writes/rationale
visible_edge_attributes: condition
concept_overrides:
  description_known, terms_known, optional local_terms
forgetting:
  baseline/node/edge/property probabilities
  max_retries, allow_shortcut_contraction
```

`ForgettingConfig` validates all probabilities in `[0, 1]` and retries as
positive. Phase 9 defines the policy value object; Phase 10 consumes its
effective probabilities for local stochastic sampling, bounded rejection
retries, and safe shortcut contraction.

`StakeholderKnowledge` is a separate private world model, not an evaluator
view. It contains `StakeholderKnowledgeGraph` with stakeholder-local opaque
node/edge/concept IDs, value references, known absence (`None`), explicit
`DONT_KNOW`, local concept descriptions and terminology, structural SOURCE/SINK
metadata, protected structural boundary edges, local-to-Truth mappings, and
shortcut metadata/provenance (`is_shortcut`, `contracted_nodes`,
`derived_from_edges`). Truth IDs and canonical terminology are private mapping
metadata and are not included in `ScenarioDefinition.prompt` or any public
scenario API.

The local graph's pure address contract is implemented by
`resolve_semantic_address()` and `StakeholderKnowledgeGraph.resolve()`. It
supports node/slot/list-element addresses, edge/condition addresses, and bare
local concept IDs. `InvalidSemanticAddressError` distinguishes malformed
syntax from `UnknownSemanticAddressError` for valid-but-missing local objects;
`try_resolve_semantic_address()` is the non-raising convenience form. No
Semantic Response Plan, sidecar parser, realization, or annotation validator
is included.

All Phase 9 value models are deeply immutable Pydantic value objects, not
merely shallow-frozen models. Sequences (`local_terms`, concept terms,
reads/writes, and shortcut metadata) are stored as tuples. Mapping fields use
the standard library's read-only `MappingProxyType`; field serializers expose
ordinary JSON objects, and Pydantic validation still accepts ordinary
list/dict input. Profile maps, local graph maps, concept terms, and
reads/writes references are normalized so construction order does not change
meaning or `model_dump_json()` output. `StakeholderKnowledge` and
`KnowledgeCoverageView` remain deliberately separate: the former constrains
future stakeholder speech, while the latter is only the reduced evaluator
coverage input introduced in Phase 7.

`tests/test_stakeholders.py` covers configuration and override round trips,
probability/retry bounds, value/absence/unknown distinctions, local reference
resolution, invalid/unknown address rejection, structural and shortcut
metadata, private mappings, ordering-independent serialization, and the
absence of fixture/source runtime dependencies. Existing Phase 1--9 tests and
seed 9004 graph/interview/primary parity remain unchanged.

## Phase 10 result: pure Truth-to-knowledge projection

Phase 10 adds `src/business_interview/stakeholders/projection.py` and completes
the standalone domain pipeline:

```text
canonical BusinessProcessGraph + StakeholderProfile + seed
    -> StakeholderKnowledge
    -> KnowledgeCoverageView
```

The primary API is:

```python
from business_interview.stakeholders import (
    knowledge_coverage_view,
    project_knowledge,
)

knowledge = project_knowledge(truth, profile, seed=42)
coverage = knowledge_coverage_view(truth, knowledge)
```

`project_knowledge()` rejects non-canonical Truth before sampling. It applies
business node/edge visibility, property visibility, independent concept
metadata overrides, and the three-valued slots without inventing hidden facts.
Known values become local `KnowledgeConceptRef` objects, known absence remains
`None`, and unknown values become `DONT_KNOW`. Only concepts referenced by
known projected values enter the private graph. Local node/edge/concept IDs
are deterministic index-only opaque IDs (`skn_###`, `ske_###`, `skc_###`),
while local-to-Truth mappings remain private metadata.

Structural SOURCE/SINK nodes and protected boundary edges bypass forgetting.
Forgotten business nodes are removed only through validated safe serial
contraction: exactly one predecessor and successor, both unconditional, no
self-loop or parallel relation, and never a branch/merge/conditioned path.
Shortcut edges retain contracted-node/derived-edge provenance. Unknown edges
are omitted; any resulting invalid topology is rejected rather than silently
repaired. `allow_shortcut_contraction=False` and retry exhaustion produce a
clear `KnowledgeProjectionError`.

Forgetting uses a local `random.Random(seed)` stream and never changes global
random state. Retries consume the same stream and respect
`ForgettingConfig.max_retries`. `seed=None` means private
`random.Random(None)` and is intentionally non-reproducible when forgetting is
enabled. For replay/rescore, persist the exact immutable projected
`StakeholderKnowledge` (including generation metadata), not only the seed.

`knowledge_coverage_view()` validates and derives the evaluator-only,
Truth-addressed `KnowledgeCoverageView` from `StakeholderKnowledge`; it is not
a second hand-maintained knowledge source. `StakeholderKnowledge` remains the
simulator-private world model, while canonical Truth remains the primary
evaluator target. Existing evaluator APIs and seed 9004 parity are unchanged.

`tests/test_stakeholder_projection.py` covers visibility, three-valued
properties, concept overrides, opaque ID determinism, local RNG/retries,
structural preservation, safe/unsafe contractions, provenance, deep
immutability, address resolution, and derived coverage. LLM realization,
simulator loop, Inspect AI, Environment, InterviewDB, Agent runtime, tools,
diagnostics, and provider configuration remain out of scope.

## Phase 11 result: Inspect AI deterministic replay adapter

Phase 11 keeps dependency direction explicit:

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

`inspect-ai` is in the `dev` dependency group and is not a runtime dependency
of the Pydantic-only core. The adapter lives independently under
`src/business_interview_bench/inspect_adapter/`; core modules never import
`inspect_ai`. The package entry point is:

```toml
[project.entry-points.inspect_ai]
business_interview_bench = "business_interview_bench.inspect_adapter._registry"
```

It registers the task `business_interview_bench/seed9004_replay`, the
no-model `seed9004_replay_solver`, and the `business_interview_bench/primary_scorer`
scorer. The replay dataset has exactly one sample and only minimal
identification metadata (`replay_case_id`, `scenario_id`, and
`source_commit_sha`). The solver loads and validates the packaged canonical
asset, writes four JSON-compatible dictionaries into the sample-scoped
`BusinessInterviewReplayStore`, marks the state complete, and returns it. It
never calls `generate()`, a model, an Agent, or a stakeholder simulator.
`--model none` remains safe even when an ambient `INSPECT_EVAL_MODEL` is set and
requires no API credentials.

The canonical asset is shared by tests and the production adapter at
`src/business_interview/replay_data/seed9004/`. It contains the exact normalized
AgentGraph, canonical Truth, InterviewEvaluationContext,
KnowledgeCoverageView, expected oracle, and provenance payloads. The expected
oracle and provenance are migration/test assets and are not copied into the
runtime Store. The Store contains only `agent`, `truth`,
`evaluation_context`, and `knowledge_coverage`. Offline scoring reconstructs
these four domain inputs with `model_validate()` and does not reload the
scenario catalog, read test fixture files, use the source checkout, call an
external service, or require an original fixture path.

The scorer delegates its authoritative result exclusively to
`evaluate_primary(agent, truth, context, knowledge_coverage)`. It derives the
field contract from `dataclasses.fields(PrimaryEvaluation)` and fails fast if
field count or names drift. All 41 named fields are preserved in the
Inspect `Score.value` dictionary; no new weighted total is introduced.
Inspect's public dict-valued metric selection applies standard `mean()` to the
existing `reconstruction_pass` key, which remains the headline. Primary
reconstruction covers node/edge recall/precision, semantic and
concept correctness/recall/precision, fabricated counts, and
`reconstruction_pass`; evidence/protocol diagnostics cover evidence coverage,
provenance/observation counts, and protocol fields. `knowledge_coverage` is a
context/informational field.

The live command and offline rescore are:

```bash
inspect eval business_interview_bench/seed9004_replay --model none
inspect score <generated-log>.eval \
  --scorer business_interview_bench/primary_scorer
```

Both paths produce the same 41/41 oracle fields and equal score payloads with
zero model/API calls. Inspect owns execution, logging, and rescoring; the
existing evaluator remains deterministic Business Interview domain code.

## Phase 12 result: one stakeholder response

Phase 12 keeps response semantics in the core `business_interview.stakeholders`
package, not in Inspect. `response.py` defines immutable
`SemanticResponsePlan`, `SemanticAnnotation`, `ConceptAlignmentAssertion`,
`TerminologyConfirmation`, and `StakeholderResponse` contracts. The pure
`canonical_semantic_mode()` function derives `value`, `absent`, `dont_know`,
`exists`, or `mention` from the canonical local resolver. `validate_response_plan()`
rejects unknown/Truth-only IDs and every mode mismatch before realization.
`validate_stakeholder_response()` requires exact quote/occurrence spans, full
plan coverage, no unplanned business annotations, and concept-only alignment
or terminology events. It does not infer facts from natural-language prose;
the private sidecar remains the authority. Public-message leakage protection
rejects stakeholder-local bare handles and full semantic addresses, but does
not reject Truth IDs that were never rendered to the stakeholder. Strict
`model_validate_json()` parsers do not repair fences or heuristically extract
JSON.

`prompting.py` provides pure `render_knowledge_prompt()`. It renders only
stakeholder-local visible graph elements, local concepts/terms, opaque IDs,
and explicit value/absence/DONT_KNOW states. Truth mappings, Truth IDs, hidden
facts, and external terminology are excluded.

The only Inspect-specific Phase 12 code is
`business_interview_bench.inspect_adapter.stakeholder`. It obtains the model
with `get_model(role="stakeholder", required=True)`, calls the model twice
(plan then realization), validates between calls, and retries only invalid
semantic output with a small fixed bound (default three attempts per phase).
No response-schema dependency or custom provider is used. Provider errors are
not conflated with semantic retries, and no Phase 11 Store is extended. Mock
integration tests verify two successful stakeholder-role calls, retry behavior,
and explicit exhaustion errors.

## Phase 13 result: live multi-turn interview runtime

Phase 13 adds the first live session without reviving tau2 runtime concepts:

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
Candidate Agent + thin Inspect tools │
  ↓                                  │
AgentGraph ─────── next question ────┘
  ↓
explicit completion
  ↓
evaluate_primary()

private SemanticLedger
  └── validated annotations / alignments / terminology bound to the exact
      public-message turn and Observation; never copied to Agent messages
```

The core `business_interview.runtime.LiveInterviewStore` is JSON-serializable
state for `scenario_id`, AgentGraph, raw public message records, observations,
private `SemanticLedger`, explicit protocol state, and turn counters.
`ingest_stakeholder_response()` runs the existing deterministic Phase 12
validator before atomically adding only `StakeholderResponse.message` to the
public ledger and candidate conversation. The exact observation text/turn and
the validated private annotations, alignments, and terminology are retained
in separate contracts; prose is never re-analyzed.

`business_interview.graph_mutations` is the authoritative pure mutation layer
for node/edge/concept add-update-remove, node properties, edge conditions,
explicit ABSENT/DONT_KNOW, endpoints, and Observation EvidenceRefs. The
Inspect `@tool` wrappers only read/write the live Store and delegate to these
operations. Candidate tools return only the candidate-owned AgentGraph and
public observation evidence; Truth, StakeholderKnowledge, and SemanticLedger
are not exposed.

`multi_turn_interview_solver` invokes the default/current candidate model
through Inspect's supplied `Generate` callback and invokes the stakeholder
through `get_model(role="stakeholder", required=True)`. Tool calls can mutate
the graph before a natural-language question. Each question receives one
validated stakeholder response, then one observation/ledger ingestion, before
the next candidate turn. `complete_interview` is explicit and prevents all
later stakeholder calls and graph mutations. The public-only
`get_observations` tool supplies stable observation IDs/turns/text for exact
EvidenceRef attachment without exposing the private ledger. Hard max-turn
exhaustion is stored as an incomplete protocol, not as completion.
`phase13_interview_task()`
and `phase13_primary_scorer()` exercise the actual Inspect eval path used by
deterministic MockLLM tests and pass the resulting context/graph through the
unchanged 41-field `evaluate_primary()`.

Phase 13 does not implement real-provider E2E, model comparison, calibration,
LLM-as-judge, aggregate-score redesign, or generic Environment/InterviewDB.
Those are retained as Phase 14 work.
