# Implementation and testing flow

## One iteration
1. Read task and dependencies; record acceptance IDs in a working note.
2. Inspect existing code and establish relevant baseline tests. Distinguish pre-existing failures.
3. Define expected behavior and a minimal failing example for the missing behavior.
4. Implement the smallest coherent change. Preserve user edits.
5. Run portable unit/integration tests and native checks relevant to the changed component.
6. Classify failures: environment, build, contract mismatch, memory/ABI, timeout, statistics, or regression. Repair the cause. Never turn an error into success to proceed.
7. Rerun failed checks and dependent regression checks. For changed native harnesses, reverify all built-ins before timing.
8. Review diff, update evidence/status/session log, and move to the next unblocked task.

## Current commands
`python3 scripts/check_project.py` checks the project packet and completion bookkeeping.
`python3 -m unittest discover -s tests -v` runs portable tests.
`python3 lab.py doctor` checks supported host.
`python3 lab.py verify` compiles and verifies built-ins (oracle + centered guard/RO/ABI probe).
`python3 lab.py fault-matrix` runs child-process fault fixtures and classifies outcomes.
`python3 lab.py portfolio --output results/portfolio.json` runs three-kernel oracle + native ref comparisons and cache/dependency notes.

New gates must be exposed through documented commands as they are implemented; do not document a future command as currently working.

## Required future verification matrix
| Test | Expected behavior |
|---|---|
| empty input with null pointer | returns zero, no access |
| lengths around unroll/vector boundaries | exact wrapping result |
| zeros, ones, UINT64_MAX, alternating bits, random | oracle equality |
| element-aligned offsets within cache lines | equality without alignment assumption |
| beginning/end against inaccessible guard pages | no before/after reads |
| read-only input mapping | no mutation |
| sentinel callee-saved registers/stack alignment | ABI preserved |
| infinite loop fixture | bounded timeout, controller survives |
| invalid instruction fixture | classified crash, next candidate can run |
| wrong sum fixture | rejected, never benchmarked |
| source changed after verify | rejected as stale or reverified |

Guard pages cannot detect every in-range invalid access or all non-local writes. ABI fixtures must themselves obey the ABI and be tested. A native subprocess is crash isolation, not a complete hostile-code sandbox. Use reviewed generated candidates until a stronger worker boundary exists.

## Session interruption
Save actual state; mark partially completed work in_progress or blocked. Log changed files, tests run, known failures, and exact next command. On resume, inspect repository state before trusting old status. Avoid restarting completed work without evidence of staleness.
