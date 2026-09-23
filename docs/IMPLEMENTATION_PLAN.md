# Ordered implementation plan

Each task requires the global definition of done in ACCEPTANCE.md plus its checks below. Dependencies are gates. On an unsupported host do portable independent work, but keep native prerequisites blocked; do not advance milestones on assumed results.

## T001 — Establish the host and baseline

Milestone: M001. Dependencies: none.

Implementation: Inspect source and host; capture Python/Clang versions; run portable tests and native doctor/verify/bench. Record unsupported checks explicitly.

Acceptance: On macOS arm64 all three built-ins verify and produce a report with every configured size; portable tests pass; command evidence exists.

Evidence: `evidence/T001.md`. Test flow: `docs/TEST_FLOW.md`.

## T002 — Make bootstrap artifacts traceable

Milestone: M001. Dependencies: T001.

Implementation: Capture complete build argv, compiler identity, source/harness/binary hashes and verification state. Prevent candidate ID collisions with built-in output paths; use unique run directories.

Acceptance: A source or harness edit invalidates previous verification; runs never overwrite each other; malformed names and missing files fail clearly.

Evidence: `evidence/T002.md`. Test flow: `docs/TEST_FLOW.md`.

## T003 — Define contract-driven test generation

Milestone: M002. Dependencies: T002.

Implementation: Extract kernel metadata and independent wrapping oracle; add seeded distributions and boundary lengths; preserve zero/null semantics.

Acceptance: All built-ins match the oracle; intentionally wrong sums fail; seed reproduces a failure; test code covers overflow and unroll boundaries.

Evidence: `evidence/T003.md`. Test flow: `docs/TEST_FLOW.md`.

## T004 — Add native memory and ABI checks

Milestone: M002. Dependencies: T003.

Implementation: Implement guarded mappings and read-only inputs; ABI sentinel wrapper; run fixtures in child processes and classify signals/timeouts.

Acceptance: Overread, underread, input-write, callee-saved corruption, trap and infinite-loop fixtures are rejected for intended reasons; correct fixtures pass.

Evidence: `evidence/T004.md`. Test flow: `docs/TEST_FLOW.md`.

## T005 — Enforce verification before timing

Milestone: M002. Dependencies: T004.

Implementation: Implement lifecycle states and artifact hashes; prevent measurement after failed/stale checks; retain diagnostics.

Acceptance: Fault matrix passes; changed source cannot reuse a PASS; controller survives child faults and continues; M002 evidence is complete.

Evidence: `evidence/T005.md`. Test flow: `docs/TEST_FLOW.md`.

## T006 — Implement reproducible native sampling

Milestone: M003. Dependencies: T005.

Implementation: Calibrate iterations; randomize paired order with seed; persist raw samples and host notes; add memory caps and cache-mode labels.

Acceptance: Calibration reaches declared duration or reports cap; replay reproduces order; samples contain exact iterations and elapsed time; memory caps enforced.

Evidence: `evidence/T006.md`. Test flow: `docs/TEST_FLOW.md`.

## T007 — Implement comparison and report

Milestone: M003. Dependencies: T006.

Implementation: Add seeded paired bootstrap, per-size ratios, aggregate objective, regression ceiling and inconclusive result. Capture disassembly.

Acceptance: Synthetic known wins/ties/regressions classify correctly; missing data cannot promote; report links raw samples; fresh sessions required for a speed claim.

Evidence: `evidence/T007.md`. Test flow: `docs/TEST_FLOW.md`.

## T008 — Implement offline proposal pipeline

Milestone: M004. Dependencies: T007.

Implementation: Validate proposal schema, limits, source review constraints and provenance; add mock proposer and immutable importer.

Acceptance: One valid proposal completes build/verify/measure; malformed IDs, oversized source, includes, unknown kernels and invalid parents are rejected.

Evidence: `evidence/T008.md`. Test flow: `docs/TEST_FLOW.md`.

## T009 — Add bounded search and resume

Milestone: M004. Dependencies: T008.

Implementation: Enforce proposal/time/stagnation budgets; persist each transition atomically; resume by hashes; add optional provider interface only.

Acceptance: Mock search stops on each configured bound; interruption leaves recoverable state; no stale candidate promotes; offline mode needs no API key.

Evidence: `evidence/T009.md`. Test flow: `docs/TEST_FLOW.md`.

## T010 — Expand kernels and machine experiments

Milestone: M005. Dependencies: T009.

Implementation: Add byte search and stable filter/map with contracts; run cache/dependency experiments; compare baseline and candidates per kernel.

Acceptance: At least three kernel families pass independent oracles and failure tests; reports distinguish observation from inferred explanation; no mandatory speedup.

Evidence: `evidence/T010.md`. Test flow: `docs/TEST_FLOW.md`.

## T011 — Implement semantic IR and interpreter

Milestone: M006. Dependencies: T010.

Implementation: Define typed operations, effects, wrapping semantics and ownership assumptions; implement interpreter and invalid-program diagnostics.

Acceptance: Generated small programs match independent oracles; ill-typed and unsupported-effect programs are rejected; semantics documented with examples.

Evidence: `evidence/T011.md`. Test flow: `docs/TEST_FLOW.md`.

## T012 — Implement minimal source and native lowering

Milestone: M006. Dependencies: T011.

Implementation: Add parser/type checker and lowering for sum/map/search to tested templates; retain interpreter as oracle.

Acceptance: Source examples compile and run natively; generated cases match interpreter; bounds/ownership violations rejected or checked; supported subset is explicit.

Evidence: `evidence/T012.md`. Test flow: `docs/TEST_FLOW.md`.

## Deferred work

Online adapters, Rust baselines, GPU support, networking runtime, structured concurrency and a custom assembler require separate tasks after their prerequisites. Use LANGUAGE_ROADMAP for direction. Do not claim these delivered by a small kernel prototype.
