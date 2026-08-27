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

## Phase 3 preparation

The Phase 2 public model seam is `business_interview.models`: construct a
`BusinessProcessGraph` in legacy-style form, call
`canonicalize_truth_graph()`, then use `model_dump_json()` /
`model_validate_json()` and `validate_canonical_graph()`. For Agent data,
construct an `AgentGraph` with explicit four-state slots and serialize it the
same way. The boundary helpers `business_node_ids()`,
`business_edge_ids()`, `business_entry_node_ids()`, and
`business_exit_node_ids()` are available without tau2.

Phase 3 can use this seam to introduce a narrowly scoped adapter for seed 9004
and then the deterministic comparison/evaluator path. It must first normalize
the legacy split artifact into explicit canonical Truth/Agent inputs; no
artifacts were copied in Phase 2. Do not begin with tools, environment,
simulator, LLM calls, or a compatibility layer.
