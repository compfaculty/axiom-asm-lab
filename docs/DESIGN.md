# Design and boundaries

## Research question
Can verified AArch64 assembly variants beat Clang `-O3` on a defined operation, with a measurable and repeatable advantage on one Apple Silicon machine? The initial result is about a kernel, not a whole language.

## Contract v1
`uint64_t sum_array(const uint64_t *a, size_t n)` reads exactly n elements, returns 0 for n=0, and adds modulo 2^64. For n=0 the pointer may be NULL. It has no writes or other externally visible effects. The macOS arm64 ABI applies: use caller-saved registers or preserve callee-saved registers; return in x0. Alignment follows that of `uint64_t`.

## Components
- `asm/`: fixed human-authored candidates.
- `candidates/`: reviewed AI or manual `.s` submissions.
- `src/reference.c`: optimized baseline and semantic reference.
- `src/harness.c`: separate-process differential checks and timing.
- `lab.py`: orchestrates compilation, verification, measurements, and metadata.
- `results/`: machine-readable benchmark runs.

LLVM/Clang is only an assembler, linker driver, and C baseline compiler. A new source language need not inherit C semantics. The future language front end should own a typed semantic IR; assembly generation can consume verified kernel templates at first. AI never changes the contract or decides correctness by assertion.

## Limits of v1
Differential testing cannot prove memory safety or semantic equivalence for every possible input. A wrong candidate could read out of bounds while still returning correct values. Current offset checks are not guard-page tests. Benchmark samples are sequential per candidate within each size; thermal drift and OS noise can affect results. Candidate code executes with current user privileges, so only run reviewed submissions. No AI API call, assembler encoder, language parser, GPU support, or concurrency runtime is included yet.
