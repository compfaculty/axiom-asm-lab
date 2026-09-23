# Session log

## Initial Cursor project package
- Bootstrap code supplied: scalar and four-accumulator sum, C baseline, Python controller.
- Portable controller tests passed during initial packaging. Native verification and performance have not been run on Apple Silicon in this workspace.
- Detailed project requirements, implementation tasks, self-review gates, and persistent Cursor rules added.
- Current phase: M001; no implementation milestone claimed complete.
- Next task: T001, inspect current host and establish a reproducible baseline.
- Next commands: `python3 scripts/check_project.py`, `python3 -m unittest discover -s tests -v`, then `python3 lab.py doctor` on the target Mac.

Append subsequent entries with date, task IDs, changes, commands/results, evidence paths, blockers, and exact next action.

## 2026-09-24 — T001 host baseline (M001 first demo)
- Host: macOS 26.6.2 arm64, Python 3.14.7, Apple clang 21.0.0.
- Change: `src/harness.c` — add `#define _DARWIN_C_SOURCE` so `CLOCK_MONOTONIC_RAW` compiles with `_POSIX_C_SOURCE`.
- Commands/results: `check_project.py` 0; `unittest discover -s tests -v` 0 (5 OK); `lab.py doctor` 0; `lab.py verify` 0 (clang_o3/scalar/unrolled4 PASS); `lab.py bench --samples 15 --output results/initial.json` 0 (all configured sizes).
- Evidence: `evidence/T001.md`. Status: T001 `done`.
- Blockers: none for T001. M001 still incomplete until T002.
- Next task: T002 — Make bootstrap artifacts traceable.
- Next command: inspect `lab.py` build/artifact paths, then implement T002 acceptance (hashes, unique run dirs, invalidate-on-edit).

## 2026-09-24 — T002 artifact traceability
- Change: `lab.py` unique `build/runs/<id>/` with manifests (build argv, compiler identity, source/harness/binary hashes, verification state); refuse overwrite; reject builtin candidate collisions; `ensure_fresh` invalidates on source/harness edit. Extended `tests/test_controller.py`.
- Commands/results: unittest 12 OK exit 0; `lab.py verify` 0; `lab.py bench --samples 15` 0 (unique results path); overwrite re-bench exit 1 as required.
- Evidence: `evidence/T002.md`. Status: T002 `done`. M001 tasks complete.
- Next task: T003 — Define contract-driven test generation.
- Next command: extract kernel metadata and independent wrapping oracle; add seeded distributions and boundary lengths (`docs/IMPLEMENTATION_PLAN.md` T003).

## 2026-09-24 — T003 contract-driven oracle
- Change: `kernels/sum_u64.py` contract + wrapping oracle + seeded boundary/distribution cases; harness `sum-file`; `lab.py` `oracle_check`; `candidates/wrong_sum.s`; `tests/test_sum_oracle.py`.
- Commands/results: unittest 20 OK; `lab.py verify` 0 (builtins + 115 oracle cases); `lab.py verify --candidate wrong_sum` 1 (FAIL empty).
- Evidence: `evidence/T003.md`. Status: T003 `done`.
- Next task: T004 — native memory and ABI checks.
- Next command: implement guarded mappings, read-only inputs, ABI sentinel wrapper, child-process fault classification.

## 2026-09-24 — T004 memory/ABI fault matrix
- Change: guarded RO mmap probe modes, `src/abi_wrap.s` ABI sentinels, `lab.py fault-matrix` child classification, fixtures (overread/underread/input_write/abi_corrupt/trap/infinite_loop).
- Commands/results: unittest 27 OK; `lab.py verify` 0; `lab.py fault-matrix` 0 (7/7 expected classifications).
- Evidence: `evidence/T004.md`. Status: T004 `done`.
- Next task: T005 — enforce verification before timing.
- Next command: implement lifecycle states and prevent measurement after failed/stale checks.
