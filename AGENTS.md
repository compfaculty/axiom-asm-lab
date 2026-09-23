# Axiom: instructions for implementation agents

## Mission
Build an assembly-first research platform on macOS Apple Silicon, then derive a safe high-level language from measured, reusable computational patterns. Preserve the complete vision in docs/PROJECT_SPEC.md. The supplied sum demo is a bootstrap fixture, not the finished product.

## Start every session
1. Read START_HERE.md, docs/PROJECT_SPEC.md, docs/IMPLEMENTATION_PLAN.md, docs/ACCEPTANCE.md, and project/status.json.
2. Inspect code and git status; do not overwrite user changes. Read docs/SESSION_LOG.md for the last handoff.
3. Select the first unblocked incomplete task. Inspect its dependencies, test obligations, and completion evidence. Work in small reviewable increments.
4. Check platform before native execution. Portable checks can run anywhere. An unsupported machine means native validation is BLOCKED, never passed.

## Implementation loop
State task ID and intended observable result. Implement it, add behavior tests and fault cases, run the narrow relevant suite, inspect failures, repair, and rerun. At milestone boundaries run all applicable gates in docs/TEST_FLOW.md. Update task state and handoff with exact commands, exit codes, evidence paths, limitations, and next task. Continue to the next authorized task when dependencies pass; do not stop after merely producing a plan.

## Invariants
- Preserve kernel contract, bounds, unsigned wrapping arithmetic, and ABI.
- Never weaken an oracle, remove a failing test, change input sizes, or alter a baseline just to obtain a pass or a speedup. Necessary contract changes require an ADR and invalidate previous evidence.
- Never fabricate native execution, benchmarks, passing gates, speedups, or equivalence proofs. Mark unrun gates blocked or pending.
- Model output is a proposal. The evaluator determines acceptance. Keep candidate generation separate from trusted contracts, oracles, and measurements.
- Tests establish tested behavior; they do not establish universal correctness or memory safety.
- Keep experiments reproducible: source/binary/harness hashes, compiler flags, seed, host metadata, and raw timing samples.
- No external API cost by default. Use offline proposals until a provider and budget are configured. Do not store credentials.
- Do not introduce a custom assembler, parser, GPU backend, or broad framework before its milestone gate is met.
- Never mark a task done with TODOs, mocked success, missing evidence, or unresolved acceptance failures.

## Completion
Apply docs/ACCEPTANCE.md. Run python3 scripts/check_project.py. This checks packet structure and evidence bookkeeping, not correctness of code or honesty of evidence. Every done task needs a human-readable evidence report. End a session with working state, remaining risks, and one exact next command. Leave unrelated files intact.
