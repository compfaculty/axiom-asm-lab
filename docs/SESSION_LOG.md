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

## 2026-09-24 — T005 lifecycle before timing (M002 complete)
- Change: explicit lifecycle (`built`/`verified`/`failed`/`stale`/`measured`), `assert_measurable`, retained diagnostics JSON; fault-matrix continues after child faults.
- Commands/results: unittest 31 OK; verify 0 (lifecycle=verified); fault-matrix 0; wrong_sum 1 with diagnostics file.
- Evidence: `evidence/T005.md`. Status: T005 `done`. M002 (T003–T005) complete; `current_milestone=M003`.
- Next task: T006 — reproducible native sampling.
- Next command: calibrate iterations; randomized paired order with seed; raw samples + memory caps.

## 2026-09-24 — T006 reproducible sampling
- Change: harness `calibrate`/`bench-raw`; `sampling.py` paired schedules, memory caps, cache-mode labels; `lab.py bench` persists raw samples + host notes (schema 2).
- Commands/results: unittest 36 OK; verify 0; bench --samples 3 --seed 42 exit 0 with iterations/elapsed_ns in samples.jsonl.
- Evidence: `evidence/T006.md`. Status: T006 `done`.
- Next task: T007 — comparison and report (paired bootstrap).
- Next command: implement seeded paired bootstrap, per-size ratios, aggregate objective, regression ceiling.

## 2026-09-24 — T007 comparison and report (M003 complete)
- Change: `analysis.py` paired bootstrap / promotion gates; `lab.py compare` + otool disassembly capture; synthetic classification tests.
- Commands/results: unittest 45 OK; compare one/two session exits 0; verify 0 with disasm_*.txt.
- Evidence: `evidence/T007.md`. Status: T007 `done`. M003 complete; milestone → M004.
- Next task: T008 — offline proposal pipeline.
- Next command: proposal schema validation, mock proposer, immutable importer.

## 2026-09-24 — T008 offline proposal pipeline
- Change: `proposals.py` schema/source review/mock/import; `lab.py propose-mock` + `evaluate-proposal`.
- Commands/results: unittest 53 OK; evaluate-proposal --mock exit 0 (build/verify/measure).
- Evidence: `evidence/T008.md`. Status: T008 `done`.
- Next task: T009 — bounded search and resume.
- Next command: proposal/time/stagnation budgets with resumable state.

## 2026-09-24 — T009 bounded search and resume (M004 complete)
- Change: `search.py` budgets (proposals/time/stagnation), atomic `search_state.json`, resume-by-hash, offline provider interface; `lab.py search`.
- Commands/results: unittest 59 OK; search stops on max_proposals/max_stagnation/max_seconds; resume extends attempts.
- Evidence: `evidence/T009.md`. Status: T009 `done`. Milestone → M005.
- Next task: T010 — expand kernels and machine experiments.
- Next command: add byte search and stable filter/map kernel contracts.

## 2026-09-24 — T010 kernel portfolio (M005 complete)
- Change: `find_u8` + `map_filter_u64` contracts/oracles; C refs; cache/dependency experiment notes; `lab.py portfolio`.
- Commands/results: unittest 65 OK; portfolio PASS for three kernels; no mandatory speedup.
- Evidence: `evidence/T010.md`. Status: T010 `done`. Milestone → M006.
- Next task: T011 — semantic IR and interpreter.
- Next command: define typed IR ops/effects and interpreter with invalid-program diagnostics.

## 2026-09-24 — T011 semantic IR and interpreter
- Change: `language/` typed IR (effects/ownership/wrapping), interpreter wired to kernel oracles, SEMANTICS.md examples, rejection diagnostics.
- Commands/results: unittest 72 OK including IR ill-typed/unsupported-effect cases.
- Evidence: `evidence/T011.md`. Status: T011 `done`.
- Next task: T012 — minimal source and native lowering.
- Next command: parser/typecheck + lower sum/map/search to tested templates.

## 2026-09-24 — T012 minimal source and native lowering (M006 complete)
- Change: parser/typecheck (`.ax`), template lowering for sum/find/map_filter, native ctypes runner vs interpreter oracle, SUBSET.md, `lab.py lang-check`, disasm under `evidence/disasm/T012_*.txt`.
- Commands/results: unittest 82 OK; lang-check PASS n=3; otool disasm of compiled templates.
- Evidence: `evidence/T012.md`. Status: T012 `done`. Milestone M006 complete.
- Next: deferred work in IMPLEMENTATION_PLAN (no further tasks in packet).
- Next command: review `docs/LANGUAGE_ROADMAP.md` Stage 4+ or open ADR for next milestone.

## Verification-integrity review follow-up
- Corrected imported versus verified search states; CLI search now invokes native evaluate-proposal in a child process with a remaining-budget timeout and process-group cleanup.
- Executable hashes are checked before measurement; the normal native verifier now requires both tight guard-page orientations.
- Promotion requires raw samples, distinct run IDs, matching identities, complete objectives and 30 pairs per size. Median-only fallback removed; exact regression ceiling fixed.
- Proposal evaluation is explicitly limited to sum_u64 until per-kernel dispatch exists.
- Portable tests now skip native integration checks on unsupported hosts. Native validation remains blocked in this Linux workspace.
- T004 onward reopened as blocked pending prerequisite revalidation; historical evidence retained as history.
- Next command on macOS arm64: python3 -m unittest discover -s tests -v
- Remaining acceptance work: docs/VERIFICATION_REVIEW.md.

## 2026-09-24 — sum_u64 optimization loop (T008/T009 complete)
- Host: macOS 26.6.2 arm64, Python 3.14.7, Apple clang 21.0.0. Git `f8abcc9`.
- Changes: `evaluate.py` shared protocol/smoke pipeline; search ranking + confirmation + active-eval time budgets + resume identity; `OfflineCatalogProvider` with scalar/unrolled2/4/8/NEON; synthetic decision tests; `--smoke` non-promotional search.
- Baseline revalidation: check_project 0; 109 unittest OK; verify 0; fault-matrix 0/7. Evidence: `evidence/BASELINE_REVALIDATE.md`.
- Native search: smoke-e2e (2 measured, accepted=null); catalog-full (5 ranked, best=catalog_unrolled8 score≈0.92, accepted=null). No speed claim.
- Evidence: `evidence/T008.md`, `evidence/T009.md`. Status: T008/T009 done; milestone → M005; T010 pending.
- Next task: T010 — expand kernels and machine experiments.
- Next command: `python3 lab.py portfolio` (after reading T010 acceptance in docs/IMPLEMENTATION_PLAN.md).

## 2026-09-25 — Search review follow-up
- Reviewed 0b03584. Fixed confirmation samples.jsonl collision with per-session output directories; confirmation now receives remaining monotonic time and the original memory cap.
- Evaluator signatures are inspected before invocation: internal TypeError no longer reruns work. Malformed proposal objects are recorded as failed.
- Resume requires matching source fingerprint and seed; older state files require a new search directory.
- Tests: 116 discovered, 111 passed, five native checks skipped on Linux; bookkeeping and diff checks passed. No native performance claim.
- Plan: docs/NEXT_CURSOR_PLAN.md. T009R tracks native validation; T009H tracks remaining recovery/evidence integrity work before T010. Historical native evidence is retained.

## 2026-09-25 — T009R native validation (M004 recovery)
- Host: macOS 26.6.2 arm64, Python 3.14.7, Apple clang 21.0.0. Git `7f7915b`.
- Commands: check_project 0; unittest 116 OK; verify 0; fault-matrix 7/7; review-smoke 0; review-protocol 0 (2 attempts); resume → 5 attempts; accepted=null.
- Evidence: `evidence/T009R.md`. Status: T009R `done`.
- Next: T009H recovery/evidence hardening.

## 2026-09-25 — T009H recovery hardening
- Changes: search-dir flock; in-flight checkpoints + conservative interrupt charging; measurement evidence revalidation on resume; retryable catalog index; incumbent score policy; resume identity includes cpu_brand + normalized compiler flags (schema 3).
- Commands: unittest 127 OK; harden-smoke search 0.
- Evidence: `evidence/T009H.md`. Status: T009H `done`. Milestone path opens T010.
- Next task: T010 — per-kernel descriptors through shared evaluate pipeline.
- Next command: inspect `kernels/` contracts and `evaluate.py` routing; implement find_u8 then map_filter dispatch.

## 2026-09-25 — T010/T011/T012 complete (M005–M006)
- T010: per-kernel descriptors + harness_find/map_filter + wrong fixtures; `lab.py kernel-eval` PASS (3 kernels, wrong blocked); portfolio PASS.
- T011/T012: lowering bound to descriptors; child-isolated native runs; return-size checks; fresh disasm; SUBSET.md updated.
- Stage 4 deferred: `docs/ADR_STAGE4_DEFER.md`.
- Commands: unittest 134 OK; kernel-eval 0; lang-check 0; check_project 0.
- Evidence: `evidence/T010.md`, `T011.md`, `T012.md`. Status: all tasks done; `current_milestone=M006`.
- Next: M007 only after ADR implementation plan; optional expand find/map search catalogs.
- Next command: `python3 scripts/check_project.py`


