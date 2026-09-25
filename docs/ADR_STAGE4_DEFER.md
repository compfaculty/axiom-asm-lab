# ADR: Defer Stage 4 safety and concurrency (M007)

- Status: Accepted
- Date: 2026-09-25
- Context: LANGUAGE_ROADMAP Stage 4 (ownership/regions, bounds as language features, scoped tasks, cancellation) and milestone M007.

## Decision
Do **not** implement Stage 4 / M007 until M006 is re-accepted with:
1. Three kernels through the shared evaluate pipeline (T010 done).
2. Language IR + `.ax` lowering revalidated against verified kernel identities (T011/T012 done).

Stage 4 requires a dedicated design for ownership transfer, error order, foreign-call boundaries, and a cancellation/cleanup runtime contract. Shipping syntax for tasks without that contract would over-claim safety.

## Consequences
- Current language remains the explicit three-template subset in `language/SUBSET.md`.
- Next authorized language expansion after M006 is an M007 implementation plan with acceptance tests for races/cancellation—not ad-hoc syntax in this packet.
- Search and evaluate may continue expanding kernel catalogs under M005 rules without implying language memory safety.
