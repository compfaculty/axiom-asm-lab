# Architecture and interfaces

## Target modules (to be implemented incrementally)
| Module | Owns | Must not own |
|---|---|---|
| machine | capability detection and machine profile | candidate acceptance |
| kernels | contracts, generators, independent oracles | model-generated test weakening |
| toolchain | compile/link/disassemble; captured commands | performance interpretation |
| verifier | differential, boundary, ABI, fault tests | benchmark optimization |
| benchmark | warmup, scheduling, timing and statistics | semantic changes |
| storage | immutable artifacts, manifests, indexing | fabricated defaults for missing evidence |
| synthesis | proposals, mutations, provider adapters | promotion authority |
| controller | lifecycle, budgets, resume, user commands | arbitrary model-directed shell execution |
| language | typed IR, semantics, lowering | implicit relaxation of arithmetic semantics |

Keep lab.py as a compatibility CLI while extracting modules when complexity warrants. Python standard library is sufficient initially; a dependency requires a concrete use and documented installation. Keep native harness code in src/ and assembly in asm/ or immutable experiment directories. Never move code solely to create an empty architecture.

## Lifecycle
proposed -> imported -> built -> verified -> measured -> accepted or performance_rejected.
Terminal failures: invalid_proposal, build_failed, verification_failed, crashed, timed_out, unsupported. Retry creates a new attempt with a link to the previous one. Changing source or harness hashes invalidates downstream state.

## Data interfaces
MachineProfile: OS/build, architecture, CPU model, physical/logical core count when known, memory, compiler identity, feature detection evidence, power/thermal notes.
KernelContract: ID/version, signature, arithmetic rules, memory effects, alignment, permitted sizes, result order, error behavior.
Proposal: schema_version, ID, kernel ID/version, parent hash or null, hypothesis, source, expected winning sizes, provider/model metadata (or manual), prompt hash.
RunManifest: run ID, UTC timestamps, source/binary/harness/contract hashes, exact command argv, environment allowlist, seeds, timeouts, stage status, exit code/signal, raw artifact paths.
Measurement: run ID, candidate ID, size, distribution, cache mode, repetition/order, iterations, elapsed_ns, ns_per_call, checksum. Separate metadata from raw samples.

## Storage
Use experiments/<run-id>/ with proposal.json, candidate.s, build.json, verify.json, samples.jsonl, summary.json and logs. Write to temporary files and atomically rename after completion. Do not overwrite existing runs. An optional SQLite index can reference immutable directories; it is not needed for the first implementation. Raw paths supplied by proposals cannot select output destinations or compiler flags.
