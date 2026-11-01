# Published UniRoute RouteFinder with CyberGold wiring

This directory executes the actual public `RouteFinder` component from
[Uniswap/uniroute-public at 9f04cb6874a7767fbc0bf51cdfacf9e6c1637999](https://github.com/Uniswap/uniroute-public/blob/9f04cb6874a7767fbc0bf51cdfacf9e6c1637999/src/core/route/RouteFinder.ts).
The original TypeScript is preserved byte-for-byte under `upstream/`.
`VENDOR.json` records its Git blob, SHA-256 and generated artifact identities.

The source repository's [original README](upstream/README.md) states **MIT
License**. That statement is preserved verbatim. The inspected public tree does
not contain a separate LICENSE text; none has been invented here. CyberGold's
new wiring files follow this repository's existing license.

## What runs

`runtime/core/route/RouteFinder.js` is the unchanged algorithm compiled with
the root project's pinned TypeScript 5.9.3, targeting ES2022/CommonJS. The
checked-in source map includes the original source. Reproduce with:

```sh
node vendor/uniroute-public/build-runtime.cjs
# Compare the result without rewriting it:
node vendor/uniroute-public/build-runtime.cjs --check
```

Production imports the generated CommonJS file and needs no TypeScript runtime
or additional npm package. The surrounding worker only maps current pool
references into the missing model interfaces, calls `generateRoutes`, and lowers
its paths into existing forward semantic hops. It never obtains RPC state,
quotes swaps or supplies Core/Helpers economics.

The production configuration explicitly reuses CyberGold's existing three
physical AMM hop bound: `MaxHops=3`, `MaxHopsExtended=3`,
`MinRoutesThreshold=0`, `MaxExtendedRoutes=0`. These are CyberGold settings,
not claims about redacted Uniswap serving defaults. The published extended
search remains present and is exercised separately with explicit test settings.

## Missing-interface wiring

- `RouteBasic`: stores the supplied `protocol` and `path`, exactly the fields
  consumed by the published finder.
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

This integration is named **`uniroute-local`**. It is the published route finder
with the wiring above, not the private full UniRoute quote/split optimizer or
an assertion of equivalent production configuration. Candidate shapes still
compete through the common CyberGold AMM adapter and whole-plan Quoter.
