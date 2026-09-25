# Next Cursor implementation plan

## Current checkpoint
The shared evaluator, catalog candidates (including NEON), paired ranking and independent confirmation exist. Previous native results reported no accepted winner; that is a valid outcome. Review of 0b03584 found that the winning confirmation path reused the primary session's samples.jsonl directory and would collide. The follow-up fixes isolate session output directories, preserve the confirmation memory cap, use actual remaining evaluation time, avoid retrying evaluators on internal TypeError, record malformed proposals, and reject resume after source/config changes.

Portable validation: 116 tests discovered, 111 passed, five native tests skipped. The new confirmation regression uses synthetic timings through the actual report writer. It tests orchestration, not native speed.

## T009R — Validate review fixes first
1. Pull this change and run the full test suite, verify, and fault-matrix on macOS arm64.
2. Run catalog smoke search in a NEW directory. Existing states lack the new resume identity and are intentionally rejected; retain them as historical evidence.
3. Run one full protocol catalog search and resume it with unchanged code, seed, provider and sampling configuration.
4. Inspect primary/measurement.json and confirmation/measurement.json for any candidate eligible for confirmation. Each directory must contain its own samples.jsonl.
5. Do not force a real candidate to win. The deterministic integration test covers successful confirmation if all native candidates lose.
6. Record the current commit, host, toolchain, commands and reports; mark T009R done only after native checks pass.

Commands:

```sh
python3 scripts/check_project.py
python3 -m unittest discover -s tests -v
python3 lab.py verify
python3 lab.py fault-matrix
python3 lab.py search --dir build/searches/review-smoke --smoke --provider catalog --max-proposals 2 --samples 3
python3 lab.py search --dir build/searches/review-protocol --provider catalog --max-proposals 2 --samples 30 --seed 1
python3 lab.py search --dir build/searches/review-protocol --resume --provider catalog --max-proposals 5 --samples 30 --seed 1
```

## T009H — Harden recovery and evidence before expanding kernels
- Persist active evaluation checkpoints and define conservative charging for abrupt termination. Current active-time accounting does not fully charge work lost to a controller crash.
- Validate stored measurement files, executable hashes and accepted-candidate evidence before reusing persisted rankings. Source fingerprint checks do not authenticate all on-disk evidence.
- Retry the original catalog entry when an interrupted attempt is explicitly retryable; do not silently skip it by advancing the proposal index.
- Add an exclusive search-directory lock to prevent two controllers writing one state.
- Preserve the incumbent unless a replacement satisfies a documented comparison policy; independently beating Clang is not proof of beating the incumbent.
- Strengthen session identity to include concrete CPU identity and normalized compiler configuration for both variants.

Acceptance: interruption tests at compilation, sampling and confirmation; corrupted evidence rejected; concurrent controller rejected; unchanged resume works; failed confirmation preserves incumbent. Synthetic tests must remain separate from native measurement evidence.

## T010 — Extend the real evaluation pipeline
Introduce per-kernel descriptors for symbol, ABI, generators, oracle, verifier, baseline, sizes and distribution. Connect find_u8 first, then stable map/filter. Remove hard-coded sum routing only after each new kernel has native correctness and negative tests. Replace descriptive cache labels with actual controlled experiments and explicitly identified assumptions. Export compact, sanitized evidence summaries plus hashes of full raw reports.

Acceptance: three kernel families evaluated through the same verification and paired measurement pipeline. Wrong results, bounds violations and ABI faults block timing. No speedup is required.

## T011/T012 — Revalidate language lowering
After T010 passes, connect the typed IR/template catalog to verified kernel identities. Keep the supported subset explicit. Add generated programs, return-size validation, and native execution isolation before expanding syntax or concurrency.

## Cursor working instructions
Read AGENTS.md and this plan. Work in the order T009R → T009H → T010 → T011/T012. Preserve user changes and historical evidence. Add meaningful negative tests before declaring a gate complete. Do not mark all milestones done merely because unit tests pass. Native execution is required where specified; no fabricated speed claims or relaxed thresholds.
