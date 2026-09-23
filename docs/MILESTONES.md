# Milestones and acceptance gates

1. **M001, runnable assembly lab (this archive):** macOS arm64 build; fixed scalar and unrolled variants; Clang baseline; verify then benchmark; JSON report. Acceptance: `doctor`, `verify`, and `bench` succeed on the target Mac.
2. **M002, stronger correctness:** guard-page boundary tests in child processes, ASan-compatible reference runs, ABI sentinel checks for callee-saved registers, randomized input distributions, and differential fuzzing. Acceptance: deliberately faulty memory/ABI candidates are rejected before timing.
3. **M003, reliable performance:** adaptive iteration counts, candidate order randomization, separate processes across repetitions, thermal/power notes, confidence intervals, cache-hot/cold modes, and assembly disassembly capture. Acceptance: baseline variance is quantified; claimed improvements exceed noise across repeat sessions.
4. **M004, controlled AI search:** candidate proposal schema, patch review, per-candidate budget, immutable run manifest, and top-k comparison. Acceptance: proposed variants are compiled, verified, timed, and rejected or retained with full provenance.
5. **M005, kernel portfolio:** bytescan, transform/filter, parser, and copy kernels with explicit semantics. Acceptance: transfer of useful patterns across workloads without changing output requirements.
6. **M006, language sketch:** typed IR for reduction/map/filter, ownership and overflow semantics, lowering to tested templates. Acceptance: simple source produces correct native binaries, with measurable comparisons against Rust/C baselines.
7. **M007, concurrency/IO:** scoped task model and bounded platform IO runtime, with cancellation and ownership transfer. Acceptance: race and cancellation tests plus throughput/latency baselines.

Do not advance a candidate to the performance leaderboard unless its current hash passes the current verification suite. Reverify after every edit.
