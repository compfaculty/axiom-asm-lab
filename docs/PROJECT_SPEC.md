# Project specification

## Product and hypothesis
Axiom is a local research workbench that learns which assembly implementations perform well for a concrete machine and workload, then makes those implementations available through precise, high-level operations. The first platform is macOS arm64, with the actual CPU model recorded at runtime. Do not assume all Apple Silicon features are identical.

The initial hypothesis is that constrained AI search can produce useful implementations competitive with optimized compiler baselines. A negative result is valid. Completion does not depend on beating Clang. The ultimate goal is a readable native language with predictable memory behavior and structured concurrency; those properties require language semantics and verified lowering, not just fast assembly.

## Functional requirements
- F01: detect host OS, architecture, CPU identity, toolchain and available capabilities; fail clearly for unsupported execution.
- F02: register kernels with typed input/output contracts, overflow semantics, memory effects, ABI, and deterministic generators.
- F03: assemble/link reviewed candidates without translating their algorithms through C.
- F04: run every candidate through differential, memory-boundary, ABI, and timeout checks before measurement.
- F05: collect reproducible timings for baseline and candidates with identical workloads and meaningful uncertainty estimates.
- F06: preserve immutable experiment artifacts and record failures as well as successes.
- F07: import model proposals with provenance and evaluate them through the same pipeline as manual proposals.
- F08: enforce search budgets and stopping criteria; resume interrupted searches without reusing stale evidence.
- F09: export a concise report and machine-readable data, with no universal speed claims from one kernel.
- F10: after multiple kernel studies, define typed IR and compile a small high-level source subset into tested implementations.

## Quality requirements
Correctness precedes optimization. Evaluation must be deterministic where possible; performance measurements are statistical. Build and result artifacts must be traceable to exact inputs. Errors must distinguish compilation, verification, crash, timeout, unsupported host, and performance rejection. A rejected candidate must not corrupt accepted results.

## Scope boundaries
The bootstrap has one kernel: unsigned 64-bit sum modulo 2^64. Later kernels: byte search, filter/map with stable order, fixed-format binary parsing, copy, and parallel reduction. Each gets its own contract. Initial execution is normal user-space code through the macOS ABI. Initial model integration is offline; network models are optional adapters. Distributed training, a custom machine-code encoder, new OS, general GPU compiler, and package ecosystem are deferred.

## Success
A new developer can open the folder, run portable checks, verify native kernels on the target host, execute a bounded reproducible search, and inspect why each candidate was accepted or rejected. The record distinguishes tested, inferred, and formally proved properties. Later success means a small language can express several kernels clearly with safe memory access and reproduce their semantics through native lowering.
