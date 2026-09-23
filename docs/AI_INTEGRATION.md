# AI integration contract

An AI model can propose AArch64 assembly candidates, but does not adjudicate correctness. The starter uses a local submission boundary with no provider dependency or secrets. Human or automated code places a reviewed `candidates/NAME.s`; then the controller compiles, verifies, and benchmarks by NAME.

## Proposal format for a later agent

Provide: (1) candidate ID and parent SHA-256; (2) optimization hypothesis; (3) full `.s` source exporting `_sum_array`; (4) ABI, bounds, and overflow reasoning; (5) predicted winning size range. One assembly file per proposal. An agent must not alter `src/harness.c`, `src/reference.c`, or the contract while pursuing a speedup.

## Evaluation loop

1. Establish baseline results and record hardware/toolchain metadata.
2. Ask the model for one change with a falsifiable hypothesis.
3. Review source and compile candidate in a separate executable.
4. Verify before timing; reject failed, crashed, or timed-out variants.
5. Benchmark and store source hash, inputs, provenance, and full samples.
6. Compare by size and repeat promising variants across sessions.
7. Promote only if improvement exceeds measurement variation without regressions that violate a chosen objective.

Future automation should use a restricted worker with CPU/memory/time limits and no access to secrets or network. Candidate submissions are native executable code; a subprocess timeout alone is not a security boundary. Retain failures to avoid proposing the same ineffective variants repeatedly. Keep API credentials outside the repository. Model provider integration can be an optional adapter that emits the proposal format, leaving the deterministic evaluator unchanged.
