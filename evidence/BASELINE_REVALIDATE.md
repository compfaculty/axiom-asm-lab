# Evidence: baseline revalidation (post integrity review)

## Change and acceptance mapping
- Task: Re-open T004–T007 gates on current checkout before optimization-loop work.
- Requirement: Native verify, fault-matrix, and portable tests must pass on macOS arm64; do not trust historical milestone claims.
- Implementation files: unchanged for this step (measurement only).

## Environment and provenance
- OS/CPU/toolchain: macOS Darwin 25.6.0 arm64, Python 3.14.7, Apple clang 21.0.0 (clang-2100.3.34.2)
- Git: `743e826f3a06da10dd0794b179df1980bd32f500` (master)
- Host machine: `arm64`

## Executed checks
| Command | Exit code | Observed result | Artifact |
|---|---|---|---|
| `python3 scripts/check_project.py` | 0 | PASS packet/task bookkeeping | stdout |
| `python3 -m unittest discover -s tests -v` | 0 | 95 tests OK | stdout |
| `python3 lab.py verify` | 0 | clang_o3/scalar/unrolled4 PASS | `build/runs/20260923T232558_7e38ccea/manifest.json` |
| `python3 lab.py fault-matrix` | 0 | 7/7 expected classifications OK | `build/runs/20260923T232600_9888f384/fault_matrix.json` |

Fault matrix (native):
- scalar → pass
- overread → memory_fault
- underread → memory_fault
- input_write → memory_fault
- abi_corrupt → abi_fail
- trap → trap
- infinite_loop → timed_out

Existing local artifacts inspected (historical, not re-claimed): `results/`, `build/searches/{first-native,t009_*}`.

## Failure tests
Fault-matrix deliberate fixtures continue to fail for intended reasons.

## Limitations
- This note revalidates correctness gates only. Full 30-sample protocol bench and search ranking were not re-run in this step.
- T008/T009 remain incomplete until shared protocol evaluate + ranking/confirmation land.

## Decision and next action
Pass for T004–T007 revalidation. Next: extract shared evaluation pipeline (`evaluate.py`) and wire protocol search measurement.
