---
title: CyberGold Quoter foundation
doc_type: architecture
status: active
owner: backend-maintainer
created: 2026-10-26
last_reviewed: 2026-10-26
canonical_for: Quoter component entry point and initial observation corrections
---

# CyberGold Quoter foundation

`cybergold_candidate.quoter.Quoter` is the production whole-plan component.
Runtime construction uses that name. The existing `universal_quote` module is
an HTTP/import compatibility adapter: `UniversalQuotes` references the same
class, and `/api/quotes/universal-exact-input` keeps its existing contract.
There is one implementation and one Uniswap SDK calculator.

This first slice preserves both search passes, the eight scalar allocation/order
choices, Core previews, private candidate pool state, retained-input accounting
and the five-second/first-usable-extension stopping policy. A normal zero-output
conversion now tries its existing alternatives; an all-zero conversion retains
its ordinary outcome. Completed scalar results compare net requested output,
then lower declared input funding on equal output. This does not construct a
reduced-funding plan or order incomparable basket vectors by summed raw units.

## Measurements

Completed JSON quotes expose optional `metrics` alongside their economic terms:

- `timeToFirstWholePlanMs`: producer start to first completed qualified plan.
- `searchMs`: producer start to the earlier of selection-clock stop or completion
  of owned search work, before terminal canonical verification.
- `totalMs`: producer start through required finalization.
- `selectionReason`: existing complete/initial/extension/timeout clock outcome.

Context acquisition belongs to the producer time. The existing selection,
canonical and cleanup clocks remain separately available. `finalizationMs` for
this response is `totalMs - searchMs`, including delayed canonical verification
even when search ends naturally. These fields are not client network time or
browser navigation time, and unit-fixture timings are not deployment benchmarks.

## Exact observations and pool reuse

Canonical Market samples retain their own block/request/route/fee coordinates.
Matching raw-route samples are used before the existing fee transformation once;
legacy/mismatched points use the existing local baseline. The same immutable
Mainnet observation boundary as the pool store applies to exact reuse. Mutable
Sandbox same-header observations remain advisory rather than becoming an exact
match solely through a block hash. No generalized curve or cross-size scaling
is enabled by this correction.

Same-pool/hash Mainnet bitmap/tick coverage merges on publication, reload and
transactional PostgreSQL saves. Different-hash replacement and Sandbox fresh
same-header acquisition retain their current behavior. Monitoring now reacquires
a replacement block at equal height through the existing snapshot path.

Focused regressions are in `test_quoter_foundation.py`,
`test_market_sample_observations.py` and `test_snapshot_copy.py`, included in the
existing local suite. `native_pool_observation_reuse.py` exercises two actual
database pools and concurrent writes against an explicitly caller-owned
`DATABASE_URL`, without RPC. It does not create or mutate a deployed database.

## Remaining migration

The existing response still packages an executable plan. Deadline-free economic
request/result types, reusable selected-plan evaluation, `/api/economic-quotes`,
`/api/tx-preparations`, shared completed-quote storage and the frontend lifecycle
are subsequent work. The class/package extraction alone does not complete those
boundaries. Universal Router remains execution infrastructure behind the
adapter; Uniswap onchain Quoter is a distinct integration scheduled for cleanup.
