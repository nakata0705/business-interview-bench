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

Phase 3 is complete for one fixture only:
`tests/fixtures/seed9004/`. The generation tool is
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

Primary migration is complete at Phase 7. Phase 8 is the next boundary for
runtime/integration work and any broader stakeholder-knowledge or compatibility
surface; it is not started here.
