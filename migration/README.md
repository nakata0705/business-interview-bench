# Migration notes

## Phase 1–2 contract

- `tau2-bench` on the `business-interview` branch is the **migration oracle**.
- The source repository is read-only for this phase. Do not change its code or
  discard any pre-existing working-tree changes.
- The new project does not need to preserve tau2's internal structure,
  backward-compatible import paths, class hierarchy, CLI, or generic framework
  abstractions.
- What must be preserved is the meaning of a Business Interview and its
  evaluation results, not tau2 implementation details.
- Future golden/parity tests will compare the new evaluator with the old
  evaluator on saved inputs and deterministic cases; this begins in Phase 3.
- Provenance metadata and saved real-LLM artifacts are diagnostic and
  comparison material. They are not, by themselves, a replacement for the
  evaluator's primary inputs or a reason to call a real LLM in tests.

## Phase 2 status

The tau2-free Truth/Agent graph model is implemented in
`src/business_interview/models/`. It includes explicit Agent epistemic states,
canonical SOURCE/SINK validation, deterministic canonicalization, and JSON
round-trip coverage. Evaluator, stakeholder knowledge, simulator, and runtime
integration remain deferred.

See `migration/inventory.md` for the source snapshot, dependency boundary,
evaluator entry points, and Phase 3 parity candidates.
