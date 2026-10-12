# Unified CYGLD trading

`POST /api/quotes/trade/stream` accepts a buy/sell intent, exact input or
requested output, a counter-token, raw amount, recipient, deadline and
slippage. Backend resolves the cached supported adapter and constructs Core
basket targets. App does not choose issuance, redemption or a market swap.
Existing family APIs remain available to older clients and specialist flows.

The coordinator runs complete eligible Core and market candidates at one
pinned block. Initial PAXG ERC20 trades compare both; existing other-token and
native ETH intents retain Core execution. Native requests use WETH as the
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

Mixed exact-output, cross-family input splitting, gas-adjusted ranking, actual
partial fills, arbitrary hooks and wider market token UI remain deferred.
This source introduces no contract deployment, server broadcast or new
operational approval requirement.
