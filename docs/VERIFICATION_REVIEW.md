# Verification integrity follow-up

This change addresses reproducible review failures at commit 1451a27. Historical evidence is preserved, but T004 onward must be revalidated against current code and actual acceptance requirements.

## Changed behavior
- Search's import-only evaluator returns `imported`. CLI search explicitly invokes native `evaluate-proposal`, recording a measured result only when a successful child report includes passing verification/oracle evidence and samples. Child errors/timeouts are failures. The remaining wall budget bounds the child process group.
- Search measurements are pipeline checks, not performance promotion. No improvement score is invented. Paired baseline scoring, two-session promotion, and richer resume/recovery remain work for T009; it is blocked rather than declared complete.
- Every measurement gate checks the executable's current hash as well as source/harness/wrapper hashes.
- Normal verification runs read-only beginning/end guard-page probes and ABI checks. Probe-specific CLI commands still emit PASS independently for fault-matrix checks.
- Comparison rejects reports lacking verified raw evidence, predefined sizes, valid finite timing counters, or at least 30 samples. Two matching reports with different run IDs are required; duplicate run identities do not promote. Identity checks cannot prove physical independence or authenticate fabricated data; honest recorded sessions remain required.
- Proposal IDs for find/map-filter are rejected until their own harnesses and oracles are connected. Language templates and portfolio code remain available.

## Native validation required before merge
On Apple Silicon with Clang:

```sh
python3 scripts/check_project.py
python3 -m unittest discover -s tests -v
python3 lab.py verify
python3 lab.py fault-matrix
python3 lab.py search --dir build/searches/integrity-native --max-proposals 1 --max-seconds 300
python3 lab.py bench --samples 30
```

Inspect the search attempt: it must have measured verification evidence, not a dry import. Use a new search directory when repeating. Run a second benchmark independently and compare those output paths. Supplying one session twice must never produce a speed claim.

## Remaining work
- Per-kernel candidate dispatch, actual machine measurements, and reproducible published evidence for T010.
- Native tests for ABI SIMD callee-saved state and broader boundary lengths (partially covered by NEON catalog oracle verify).
- Revalidate language milestone prerequisites and update stale bootstrap descriptions.
- Online provider adapters (explicitly deferred).

## Closed in optimization-loop follow-up (2026-09-24)
- Shared protocol evaluate pipeline (`evaluate.py`); search ranks via paired baseline scoring; confirmation uses existing promotion gates; active-eval time budgets; catalog provider with real asm variants; smoke path cannot promote.
- Native catalog-full search: five candidates ranked; none accepted; best observed `catalog_unrolled8` (score ≈0.92 vs clang_o3). See `evidence/T009.md`.

Portable + native validation for the loop: 109 tests OK; verify and fault-matrix revalidated; protocol search measured on macOS arm64.
