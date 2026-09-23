# PR notes: sum_u64 optimization loop

Pushed to `origin/master` as commits `67bf7f9`…`86ce866`. `gh` is not authenticated in this environment, so no GitHub PR object was created. Use this text when opening a PR from a branch, or treat the master push as the reviewable delivery.

## Summary
- Shared `evaluate.py` protocol/smoke pipeline for `bench`, `evaluate-proposal`, and search.
- Search ranks vs `clang_o3`, confirms only when first session is promote-eligible, separates `best_observed` from `accepted`.
- Time budget = active evaluation seconds; resume validates evaluation config identity.
- Offline catalog: scalar, unrolled2/4/8, NEON; mock provider retained; `--smoke` cannot promote.

## Native result (catalog-full)
All five candidates ranked slower than Clang; `accepted: null`; best observed `catalog_unrolled8` ≈0.92×. Artifacts under `build/searches/catalog-full/` (local).

## Test plan
- `python3 scripts/check_project.py`
- `python3 -m unittest discover -s tests -v`
- `python3 lab.py verify` / `fault-matrix`
- `python3 lab.py search --smoke --provider catalog --max-proposals 2 --samples 3`
- `python3 lab.py search --provider catalog --max-proposals 5 --samples 30`

## Limitations
- No speed claim; confirmation path exercised synthetically.
- Next: T010 kernel portfolio.
