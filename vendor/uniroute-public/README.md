# Published UniRoute finder and quote/split components with CyberGold wiring

This directory executes the actual public `RouteFinder` component from
[Uniswap/uniroute-public at 9f04cb6874a7767fbc0bf51cdfacf9e6c1637999](https://github.com/Uniswap/uniroute-public/blob/9f04cb6874a7767fbc0bf51cdfacf9e6c1637999/src/core/route/RouteFinder.ts).
The original TypeScript is preserved byte-for-byte under `upstream/`.
`VENDOR.json` records its Git blob, SHA-256 and generated artifact identities.

The same source pin now also executes its unchanged `BaseQuoteStrategy`,
`DeepQuoteStrategy`, `QuoteBestSplitFinder`, `RouteQuoteAllocator` and
`SimpleQuoteSelector`. Their exact Git blobs, source SHA-256s and generated
artifacts are recorded together in `VENDOR.json`.

The source repository's [original README](upstream/README.md) states **MIT
License**. That statement is preserved verbatim. The inspected public tree does
not contain a separate LICENSE text; none has been invented here. CyberGold's
new wiring files follow this repository's existing license.

## What runs

The six components are compiled with the root project's pinned TypeScript
5.9.3, targeting ES2022/CommonJS. Each checked-in source map includes the
original source. Reproduce with:

```sh
node vendor/uniroute-public/build-runtime.cjs
# Compare the result without rewriting it:
node vendor/uniroute-public/build-runtime.cjs --check
```

Generated JavaScript deterministically strips trailing horizontal whitespace;
the upstream source bytes and compiler-generated source maps are preserved.

Production imports generated CommonJS and needs no TypeScript runtime or new
npm package. The surrounding worker maps current pool references into the
missing model interfaces and calls the actual `generateRoutes`. It publishes
those original semantic linear hints immediately, before waiting for any deeper
quote work. Explicit native transitions and the original pool references stay
with each path. No RPC transport, Core preview or Helpers economics runs in
the calculation child.

The production configuration explicitly reuses CyberGold's existing three
physical AMM hop bound: `MaxHops=3`, `MaxHopsExtended=3`,
`MinRoutesThreshold=0`, `MaxExtendedRoutes=0`. These are CyberGold settings,
not claims about redacted Uniswap serving defaults. The published extended
search remains present and is exercised separately with explicit test settings.

`DeepQuoteStrategy` quotes each linear path at 5% increments, using only the
Python owner's canonical SDK callbacks with fresh candidate state. Its actual
split finder searches up to two branches, and its actual allocator stitches
the quoted combinations. Zero gas details express a raw-output nomination
objective. `SimpleQuoteSelector` orders **all** stitched nominations; no top-one
AMM selection or result quota is imposed on the Quoter. The split timeout is
`Infinity`, so the existing Python QuoteBudget remains the sole selection
clock and owns process cancellation. The missing event-loop slicer yields
cooperatively; it does not introduce another deadline.

Deep candidates encode exact percentage weights as decimal-string `amountIn`
values (for example `35` and `65`). The existing AMM adapter sets actual
runtime funding and final-branch integer remainder. Percentage callbacks are
nomination observations only: their separately floored input amounts and
summed output cannot replace the final ordered, private-bank whole-plan replay.
Raw finder hints remain available even when a callback is unquotable, partial
or fails, or when the deeper calculation ends with an ordinary error.

The upstream split search excludes shared physical pools and conflicting
native/WETH endpoint classes and admits at most two unused paths per percentage.
These remain nomination limitations of this component. They never reject raw
finder hints or other tools' supported shared-pool plans. In particular, two
Market paths sharing CyberGold's Core anchor cannot become a split through this
algorithm, while disjoint basket-acquisition alternatives can. The custom
producer remains available alongside it.

Tests and comparison tooling can override the owned worker command with
`--finder-only` or `--split-percentage=25`; `--split-percentage=5` also selects
the default. These constructor command variants add no environment gate or
public RouteQuery field.

## Missing-interface wiring

- `RouteBasic`: stores `protocol`, `path` and `percentage`, and supplies a stable
  route string for per-percentage deduplication. `QuoteBasic`/`QuoteSplit` retain
  the fields consumed by the published orchestration and allocator. The
  unpublished TradeType enum is mapped internally; the worker stays exact-in.
- Address/pool quote models: minimal string/equality methods represent the
  existing canonical physical execution key, including V4 fee/spacing/hooks.
  Alias IDs and address formatting never create independent liquidity. Pool
  directions and native transitions are lowered from the original finder paths.
- Address/pool models: the worker supplies plain `lowerCased` address objects,
  protocol values matching CyberGold's existing V2/V3/V4 discriminants, the V4
  tick spacing and the original physical pool reference. Type-only imports for
  those absent classes and `@uniswap/lib-uni/context` are erased by TypeScript.
- `config`: provides metric-key identity and an unused chain-name table. No
  private metrics context is passed; the actual caller chain ID is retained,
  including Sandbox 31338.
- `poolUtils`: provides the missing model-only native/WETH connectivity edge
  and sentinel spacing `-1`. This represents the existing lossless transition,
  never a physical pool or liquidity observation. Both native and wrapped endpoints are projected
  through the original finder and restored with explicit 1:1 transitions. This
  covers a terminal transition after three physical pools; the finder itself
  grants its extra fake hop only after that edge is already in its path.
  Adjacent inverse transitions and duplicate nominations are removed. The
  three physical AMM hop bound is unchanged. No chain is relabelled as Mainnet.
- `CanonicalPools` and `RoutingBlockList`: the unavailable private policy
  interfaces pass through CyberGold's supplied inventory. No private allowlist,
  inactivity filter or new eligibility rule is invented. Existing configured
  producer acquisition and canonical SDK replay retain their responsibilities.
- Quote fetcher: asks the Python owner for each route/percentage observation.
  No local SDK reserve placeholder or remote output becomes a price oracle.
  One callback failure leaves other percentages available; incomplete search
  errors cannot retract the already-published raw hints.
- Gas/token/L2 helpers: injected zero-gas services avoid remote gas conversion,
  calldata generation and private token services. Unavailable private metrics
  are no-ops; environment parsing only supplies the published component's
  optional diagnostic defaults. The fixed positive cooperative slice needs no
  runtime admission predicate.
- Aggregator-hook helpers: all supplied paths stay on canonical callbacks.
  Missing private hook classification/telemetry does not introduce an allowlist,
  filter a path, call a remote `hook.quote()` or claim its execution semantics.

This integration remains **`uniroute-local`**. It now executes the published
finder, quote strategy, split search, allocator and selector with the wiring
above. It does not reproduce the private full UniRoute service, discovery/cache
infrastructure, remote hook execution or redacted serving configuration.
Candidate shapes compete through the common CyberGold AMM adapter and
whole-plan Quoter; no Uniswap production-parity claim is made.
