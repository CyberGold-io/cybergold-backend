# Unified CYGLD trading

`POST /api/quotes/trade/stream` accepts a buy/sell intent, exact input or
requested output, a counter-token, raw amount, recipient, deadline and
slippage. Backend resolves the cached supported adapter and constructs Core
basket targets. App does not choose issuance, redemption or a market swap.
Existing family APIs remain available to older clients and specialist flows.

The coordinator runs complete eligible Core and market candidates at one
pinned block. ERC20 counter-tokens compare both providers through the typed
adapter. Every Market branch begins with the configured canonical CYGLD/PAXG
pool for a CYGLD sale, or ends with that pool for a CYGLD purchase. PAXG itself
uses only that canonical pool. Other ERC20s add PAXG connectors within the
existing three-hop bound. Discovery retains selected V2/V3/V4 inventory and
direct/via-WETH V3 connector identities; this is not a claim that every V4 pool
has been discovered. Another CYGLD pool cannot replace the canonical edge.

A cold API can also try direct PAXG/counter-token hookless V4 keys for the
common fee/spacing pairs `100/1`, `500/10`, `3000/60` and `10000/200`.
StateView initialization and the existing SDK quote establish whether each
candidate exists and executes; a guessed key is not an existing pool. Successful
identities retain a canonical acquisition anchor for reuse and reorg recovery.
The worker separately catches up PAXG V4 Initialize events in bounded ranges
from the PoolManager's deployment, with its own `v4-paxg` cursor. The older
Core-only cursor cannot establish that coverage. Other acquired fee/spacing
keys stay eligible; no negative seed observation prunes them. Catalog catch-up
and complete directional liquidity/tick coverage remain different facts.

Mixed-protocol exact-input routes use the existing measured per-hop adapter.
Exact-output routes remain homogeneous: the canonical V4 edge therefore needs
an all-V4 connector path. Mixed-protocol exact-output paths remain excluded;
if no eligible complete route is found the ordinary no-route/deadline result
remains distinct from proven insufficient liquidity. Fees, execution bounds,
selection objectives and the existing partial-input/refund behavior are unchanged.
Retained Market plans revalidate the same anchor, rather than admitting an
unanchored caller hint. Core sourcing routes retain their existing coverage.

Native ETH intents retain Core execution. The deployed Market facet funds and
settles ERC20s and has no payable wrap/unwrap entrypoint; exposing its WETH quote
as native ETH execution would be incorrect. Native requests use WETH as the
counter-token with `native: true`; the actual endpoint and Core helper token
are the native zero address. The historical V3 adapter keeps Core's legacy
compiler; it cannot decode the market provider's typed payload, so that market
alternative is unsupported rather than replacing a valid Core result.
Neither a failed competitor nor its slow search
tail removes an available qualified incumbent. Provider errors are tagged;
a proved noncanonical common snapshot invalidates its dependent candidates.

Exact-input ranking maximizes quoted recipient output after each family's
existing fees. Exact-output ranking minimizes quoted payer input including
fees. Funding ceilings and delivery minima remain separate; gas is displayed
separately. Equal quoted economics deterministically prefer Core. Recovery
shares and other asset remainders retain their actual recipient/refund roles
but are not valued as the requested counter-token.

Core issuance executes a fixed net CYGLD target and refunds unused acquired
input, including when the user entered an input budget. Its quoted input is
the expected reserve sourcing cost, rather than the funded ceiling. Core
output-targeting redemption still executes an exact gross CYGLD burn with a
minimum counter-token payout; its quoted input is the complete fixed burn,
not the advisory unprotected `expectedInputAmount` inversion. Counter-token
surplus and positive recovery shares reach the configured recipient. Market
exact-output execution retains its own fixed output, fee and input refund
semantics. Market fees are not applied to Core sourcing legs or charged again
by aggregation.

`TradeQuote` carries normalized quoted input/output and min/max bounds with an
explicit `strategy`, intact `providerRequest` and `providerQuote`. The App
dispatches that complete plan through existing Helpers functions. A tagged
`retainedPlan` freshly revalidates only the selected family and its literal
limits; changing the execution family is a fresh search. Wallet authorization,
signed full-call simulation and receipt accounting remain family-specific.
Search updates cannot replace a plan already captured for signing.

`POST /api/quotes/trade/model` returns separate organic family packets and a
Backend-ranked indicative estimate. Warm packets use paid observations without
RPC. Cold acquisition reuses existing lightweight Market baselines and Core
display-state acquisition; missing models do not block exact work. Hypothetical
SDK state remains isolated per candidate. Request sharing, shared pool reads,
provider deadlines, bounded concurrency, last-subscriber cancellation and
existing fork/generation invalidation are retained. First qualified latency and
full-search latency are distinct; one HTTP request does not imply one RPC read.

Capacity failures keep the existing canonical Helpers preview as authority.
An explicit CYGLD issuance output is previewed before collateral route search;
an explicit CYGLD redemption input is previewed before output route search.
`issuance-cap-exceeded` retains the contract's gross requested increase, current
supply, limiting cap and remaining gross capacity in `constraint`. The
`limitKind` distinguishes maximum total supply from the effective recovery cap.
`redemption-supply-exceeded` identifies a focused exact-input redemption rejected
because its post-Helpers-fee Core input exceeds total supply; its requested raw
amount is the outer CYGLD input, not a collateral amount or wallet balance.

Core uses the same `InsufficientSupply()` ABI error for exact-output collateral
minima above reserves and for their computed gross redemption above supply.
That focused failure is therefore `redemption-capacity-exceeded`; it does not
claim to distinguish those two causes or invent missing available quantities.
The generic compatibility decoder retains `insufficient-protocol-supply` when
no focused preview method is known. Diagnostics add no RPC reads or retries.

A token-output redemption may need inverse route observations before its Core
minimum vector exists. A search deadline before that preview is a quote timeout,
not evidence of a supply or reserve failure. Weighted seed allocation and nominal
USD size cannot prove that every route is infeasible. Core failures remain
provider-specific so an eligible Market candidate can still qualify and win.
Input-budget issuance continues to permit the existing cap-limited fixed output
and input refunds; a large budget alone does not require a cap rejection.

Mixed exact-output, native ETH Market execution, cross-family input splitting,
gas-adjusted ranking, arbitrary hooks and basket Market composition remain deferred.
This source introduces no contract deployment, server broadcast or new
operational approval requirement.
