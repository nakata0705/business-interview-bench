# Migration notes

## Phase 1–3 contract

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

### Phase 4 entry point

Phase 4 can begin with `truth.json`, `agent.json`, and the primary oracle
fields in `expected.json`, using `provenance.json` to pin the source commit and
artifact hashes. The minimum first component is deterministic
AgentGraph-to-TruthGraph alignment/comparison against those fields. A future
full evidence/knowledge replay would require separately designing safe
normalized observation and stakeholder-input contracts; it is not part of
Phase 3. No evaluator, comparison, matcher, scoring, stakeholder, simulator,
or runtime implementation has been started here.
