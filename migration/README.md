# Migration notes

## Phase 1 contract

- `tau2-bench` on the `business-interview` branch is the **migration oracle**.
- The source repository is read-only for this phase. Do not change its code or
  discard any pre-existing working-tree changes.
- The new project does not need to preserve tau2's internal structure,
  backward-compatible import paths, class hierarchy, CLI, or generic framework
  abstractions.
- What must be preserved is the meaning of a Business Interview and its
  evaluation results, not tau2 implementation details.
- Future golden/parity tests will compare the new evaluator with the old
  evaluator on saved inputs and deterministic cases.
- Provenance metadata and saved real-LLM artifacts are diagnostic and
  comparison material. They are not, by themselves, a replacement for the
  evaluator's primary inputs or a reason to call a real LLM in tests.

See `migration/inventory.md` for the source snapshot, dependency boundary,
evaluator entry points, and candidate parity fixtures.
