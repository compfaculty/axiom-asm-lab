# Acceptance criteria and agent self-review

## Definition of done for every task
1. Required behavior exists in source, with no placeholder success path.
2. Positive and relevant negative tests pass on the applicable platform.
3. The task's specific acceptance checks in IMPLEMENTATION_PLAN are satisfied.
4. Existing relevant checks remain green; new failures are explained and repaired.
5. Evidence report includes exact commands, exit codes, host, source revision/hashes, outputs, limitations and acceptance mapping.
6. Documentation matches implemented behavior. Deferred capabilities are labeled.
7. project/status.json points to the evidence report; SESSION_LOG records next work.

Task states: pending, in_progress, blocked, done. A blocked task needs a reason and a concrete unblocking action. Evidence is not optional for done. Documentation-only tasks can finish with document validation; native tasks cannot finish based on portable tests.

## Milestone gates
| Gate | Pass condition | Evidence |
|---|---|---|
| M001 bootstrap | portable checks pass; three built-in variants compile and verify on macOS arm64; benchmark emits all configured sizes | commands, native host, report path |
| M002 verifier | correct fixtures pass; wrong-result, overread, write, ABI corruption and infinite-loop fixtures fail for intended reasons | fault matrix and raw verifier results |
| M003 measurement | randomized paired scheduling, adaptive timing, raw samples and reproducible analysis work; invalid runs never promote | benchmark manifest, analysis tests, two sessions |
| M004 AI loop | offline proposal evaluates end-to-end; malformed and over-budget proposals rejected; resumed runs preserve provenance | offline replay and failure tests |
| M005 portfolio | at least three distinct kernel contracts and correct baseline/candidate pairs; findings distinguish kernel-specific patterns | per-kernel correctness and reports |
| M006 language | minimal source compiles and runs for sum/map/search; type/effect violations rejected; compiler results match contract oracles | language tests, disassembly, native comparisons |

No speedup is required for milestone completion. A candidate needs the separate performance gate in BENCHMARK_PROTOCOL before being called faster. Failing to beat the baseline is a valid experimental outcome.

## Self-review before claiming completion
- Did I actually execute every command I call passing?
- Are native results from the intended hardware and current artifact hashes?
- Did I test deliberate failures so the validator is capable of rejecting bad code?
- Have I preserved contract, output semantics, baseline flags, and timing scope?
- Are claims limited to measured sizes/distributions and tested behavior?
- Can a clean checkout reproduce the result with the recorded instructions?
- Are blocked gates visible, with no fabricated or stale evidence?

The bookkeeping checker verifies file references and state shape. It cannot establish that a result is true; inspect the evidence against these criteria.
