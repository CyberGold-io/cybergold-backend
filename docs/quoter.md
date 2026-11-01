---
title: CyberGold Quoter and transaction preparation
doc_type: architecture
status: active
owner: backend-maintainer
created: 2026-10-26
last_reviewed: 2026-11-01
canonical_for: Quoter economic API, selected-plan preparation and observation reuse
---

# CyberGold Quoter and transaction preparation

The local implementation separates economic quoting from transaction
preparation. It has one whole-plan Quoter in `cybergold_candidate.quoter`, one
Backend Fast Estimator and one shared Uniswap SDK Bridge. The runtime retains
`UniversalQuotes` as the temporary execution-shaped adapter for older callers;
its economic methods use that same Quoter implementation. These source changes
do not establish deployment or profile adoption.

## API responsibilities

| Endpoint | Consumes | Produces |
| --- | --- | --- |
| `POST /api/economic-quotes` | Economic Request: intent, ordered input budgets and requested output currency; optional `refresh` transport flag. | Economic Quote with a selected semantic plan, declared funding, expected net output, fees, retained inputs and original observation context. |
| `POST /api/economic-estimates` | Existing scalar `TradeModelRequest`. | Existing `TradeQuoteModelPacket`, containing the one Backend-selected advisory estimate and producer model observations. |
| `POST /api/tx-preparations` | Selected Economic Quote, sender/recipient, chosen execution tolerance and any already accepted bounds. | Unsigned Helpers execution plan, authorization quantities, newly evaluated economics and execution deadline. |

An Economic Quote has no recipient, transaction deadline, slippage minimum,
signature or encoded transaction body. Its `plan.body` contains semantic Core
and conversion instructions, not calldata. `plan.allocations` and
`plan.conversions` retain the chosen order and routes needed for replay.
`/api/quotes/universal-exact-input` remains a compatibility adapter that compiles
the old response shape, including an optional semantic `economicQuote` for
preparation. Existing clear pool/governance/Core-preview interfaces retain
their responsibilities.

## Budgets, funding and consumption

`EconomicRequest.inputs` expresses the input budget. `EconomicQuote.inputs`
expresses the plan's declared funding: the amount Helpers acquires. Direct
basket issuance also evaluates the exact input vector required by Core's
capacity-limited preview. Direct basket redemption computes its funding ceiling
from the requested budget and total CYGLD supply at the observed block, before
applying Helpers/Core fees. Available reserves and recovery shares determine
the returned redemption basket through the existing authoritative previews.
The original request remains the budget; unused funding is never acquired.

These amounts come from protocol state and integer preview calculations, not
blind smaller-amount probes. After ordinary scalar selection, the Quoter can
replay its winner and reconstruct payer-source acquisition/Market lots from
actual consumption. It preserves productive mixed branches in execution order,
solves exactly representable split weights and sale fees, then replays one
smaller-funded proposal. The ordinary output-first comparator chooses the
result. Other-currency retention is not subtracted from payer funding. A
reduction requiring branch deletion or an unrepresentable split retains the
original plan. This is one construction, not a minimum-funding solver.

`conversionObservations` records each evaluated conversion's input/output
currencies, funded input, simulated consumed input and output. Consumption is
the amount used by that conversion's actual SDK replay. It can be lower than
the funded amount. These are per-conversion quantities, potentially in
different currencies; adding their raw units does not produce whole-trade
spending. Settlement receipts remain the evidence for actual mined debits and
credits. Returned input follows the existing Helpers retained-charge policy.

Complete scalar results compare net requested output first, then lower declared
funding on an equal-output tie in the same input currency. For basket results,
matching output descriptors compare componentwise; no output may decrease.
Equal outputs prefer componentwise smaller funding in matching currencies.
Incomparable vectors keep their incumbent rather than summing unrelated raw
units. Productive full-budget continuations can still win by returning more.
This comparison does not discover smaller funding by itself.

## Shared historical quotes and explicit Refresh

The existing PostgreSQL infrastructure stores one last successfully committed
whole quote per normalized economic request and configuration scope. Scope
includes chain/Core/Helpers/adapter, fork generation and static fee-affecting
runtime policy. It excludes head, recipient, execution deadline and tolerance.
Mutable onchain Core/helper fees belong to the quote's observed block, like
pool prices; process-local knowledge of a newer fee observation does not create
a different shared lookup key.

An ordinary matching request can return the stored quote and its original
context. It is a historical observation, not a freshly executable transaction.
The new namespace is bounded to 4,096 economic records per existing
chain/Core/generation scope, with whole-record saves and oldest-save pruning.
Concurrent saves do not mix plan/output/context fields. Cache read/write errors
leave ordinary search and preparation available.

`refresh: true` bypasses using the stored quote as the answer. The Quoter may
replay its semantic plan with its saved funding as a seed, but must evaluate at
the current state. Saved funding must fit the requested budgets and, for direct
basket redemption, the current supply-derived funding ceiling.
Search success replaces the complete saved record. Search failure leaves the
previous record intact and is returned as a failed Refresh. Browser display
copies can retain that previous observation while showing the error.

## Search and selected-plan preparation

Production fresh searches use one `RouteQuery` / `CandidateFeed` API for
`CustomRoutes`, AlphaRouter, `uniroute-local`, `uniroute-api` and Guidestar.
Immediate custom candidates remain lazy; pending sources start together when
the conversion pair and amount are known. `CyberGoldAmmAdapter` consumes their
available nominations fairly and returns independently. New hints wake a
separate detailed whole-plan pass and optional family/prefix work using the
same search session; neither first-result nor detailed custom
improvements wait for a provider tail. Feeds can publish incremental batches;
each batch uses those same arrival and ownership rules. The original search
clock and pricing slots still bound this work.

Local graph-dependent tools also invalidate their nomination cache when the
canonical physical catalog changes. The session observes existing connector
and persisted-catalog completion signals, retains old offers, and coalesces a
follow-up behind in-flight work. It never waits for or cancels the shared
database load. The optional dependency marker affects cache invalidation only;
hosted API requests do not repeat for local catalog growth. Display/scalar
changes and physical aliases do not change the graph identity. Refresh work
uses the same selection clock, and detached callbacks start no work after
selection stops or the owner closes.

Both pure-Market and Market+Core plans call that AMM adapter. Tools search only
the AMM segments: they receive no Core preview, basket, fee or economic intent
work. The Quoter composes their canonically replayed segments with Core
issuance/redemption and compares complete economic plans. Market anchoring,
quick-pass seed preference, native funding and split rounding belong to the
adapter. Its raw-path projection runs before custom split construction, without
changing query sharing or the generic provider's independent path coverage.

Hints are reconstructed through the existing connected-path producer, including
native/WETH transitions, and replayed against each candidate's private pool bank.
Remote amounts, prices, recipient, minimum and calldata never become execution
terms. AlphaRouter's percentage/split selection uses canonical Python SDK quote
callbacks with zero gas for nomination; whole-plan fees and ranking remain here.
Selected-plan preparation starts no supplier discovery. All supplier tasks,
HTTP clients and calculation children are owned and drained by their search.

The private optional `CYBERGOLD_UNISWAP_API_KEY` enables hosted requests;
`CYBERGOLD_UNISWAP_API_SWAPPER` defaults to Helpers. Missing account access or
ordinary API/AlphaRouter failures leave local discovery available. Actual chain
IDs are retained: the upstream AlphaRouter configuration and Guidestar beta
do not support Sandbox 31338 as Mainnet. The wired local UniRoute components retain
actual chain 31338 and the existing three-physical-hop/native transition rules.
The unchanged published RouteFinder emits raw hints before DeepQuoteStrategy,
BaseQuoteStrategy, QuoteBestSplitFinder, RouteQuoteAllocator and
SimpleQuoteSelector produce deeper split batches through canonical callbacks.
Local model/service wiring, zero-gas nomination and source pins are documented
in `vendor/uniroute-public`. The default 5% grid searches two-branch splits;
all stitched nominations reach whole-plan evaluation under the original clock.
Upstream shared-pool restrictions do not exclude raw/custom alternatives.
These are published components with local wiring, not the private full UniRoute
service. `uniroute-api` uses the
standard Trading API path; no documented engine selector exists. Response
evidence records UniRoute/Guidestar/unverified backend attribution separately
from that integration-source name, without requiring it to use a candidate.
Internal `metrics.routeDiscovery` records provider outcomes, nomination and
completion/cancellation timing, incremental batches, worker queries, canonical
callback counts/failures/elapsed time, reevaluation, physical RPC HTTP attempts and
hosted API requests separately. Physical counts sit below coalescing: one
shared POST is charged once to its first issuing owner; a JSON-RPC batch records
one envelope and its members. A Multicall `eth_call` remains one member, without
claiming a count of its inner functions. Elapsed transport times can overlap;
their sum is not the producer's wall time. No credential, URL, parameters or
supplier error text is recorded.
Common replay/Core/canonicality RPC belongs to `cybergold-quoter`; the pure
custom graph enumerator is not falsely charged for those reads. Explicit
supplier callbacks and API identity acquisition retain their own issuer tags.

Selected conversions retain `discoveryOrigins`; `routeOrigins` summarizes the
whole quote's nominators separately from its canonical CyberGold evaluator.
Equivalent later nominations can enrich origin metadata without replacing an
economic tie. The existing whole-JSON cache retains those origins and the
original measured performance. Stored responses/logs label those measurements
historical, rather than fresh work. Progressive publication preserves later
equivalent origins through its final returned/cached quote. Prefix repair and
neighboring-amount topology reuse preserve their input route's optional source
metadata. Dormant zero-residual Core bindings record adapter composition
separately, without inventing an AMM nominator. Missing or malformed
origin metadata never prevents selected-plan replay, changes a cache key or
affects ranking. These sources nominate routes; they do not change which
economic plan wins.

The first-result and detailed passes, eight scalar allocation/order choices,
Core previews and private ordered pool replay remain. The comparison window
is five seconds. Only if no usable whole plan exists can search continue for
up to ten more seconds; its first usable result then ends selection. A
zero-output conversion tries its existing alternatives, while an all-zero
conversion retains its ordinary outcome. Optional full-budget scalar Market
routes from the same tool feeds are interleaved by currency/protocol family through the existing route
scheduler. Ordinary quick/detailed/Core/mixed/split jobs remain concurrent.
Added work has 16 route starts per search and the scheduler's eight pricing
slots; failed optional work leaves ordinary candidates available. There is no
new provider-call rejection quota or global early-stop rule.

Cold bootstrap uses fixed family order. With a supplied saved plan, optional
exploration waits for its replay attempt, then uses a request-local random
seed; ordinary work does not wait. Malformed, unavailable or budget-ineligible
seeds release exploration too. The plan is repriced at the current context;
its saved numeric output is never trusted. Higher output can use more funding
within budget; equal output can win only with lower declared funding.

Conservative fee-adjusted spot bounds prune only unpriced independent,
acyclic, zero-hook Market paths whose upper output is strictly below an exact
incumbent. Unknown bounds and output ties continue pricing. Bounds do not stop
Core, mixed, split or undiscovered work, and do not change the selection clock.
Pruning follows the active fair family order rather than sorting by the bound.
Runtime bounds use the same request-local base observations as exact replay;
a newer same-hash Sandbox registry publication cannot replace that base. A
path whose base is not acquired yet has an unknown bound and prices normally.

An intermediate partial fill can provide an optional linear-prefix proposal:
invert the preceding distinct-pool hops with exact-output SDK arithmetic at
their actual pre-states, then forward-replay a smaller-funded exact-input plan.
The repair runs sequentially under its parent task ownership and spends a
second optional start. No incomplete path becomes a quote. Shared/repeated
pools, split/Core coupling, hooks and native-prefix repairs retain ordinary
behavior. Execution and accepted bounds still use the existing exact-input
format.

Transaction Preparation replays the selected routes and allocations through
`quoter.evaluate`; it does not discover a replacement route. It binds scalar
and full Core-output minima from the selected observation and chosen tolerance
before repricing. Already accepted input maxima and frozen minima are retained.
A changed-state result that cannot meet them returns the ordinary preparation
error. It cannot lower the accepted minimum or enlarge the debit to succeed.
Helpers/adapter deployment binding is preserved so a captured wallet batch
cannot be silently retargeted.

Preparation replays the selected funding, not the original larger budget. Its
returned nested `economicQuote.request.inputs` therefore describes that replay's
funding; the selected original Economic Quote retains the user's budget. If
supply or wallet balances change after quoting, preparation does not enlarge or
silently resize the selected funding. The App's existing fresh balance check
still establishes whether the payer can fund it; preparation alone is not a
separate guarantee of wallet fundability.

After replay, preparation assigns the existing execution deadline as current
time plus 600 seconds and compiles the Helpers body. Browsing consumes none of
that lifetime; execution after the deadline fails onchain. Token permits and
Permit2 retain their own authorization expiries. The response is unsigned and
the endpoint does not broadcast. The App retains its existing post-approval
Market/mixed signed-call simulation and pure-Core advisory fee-estimation/batch
behavior.

## Estimation and pool reuse

The Fast Estimator reuses an exact route sample only when its route, request,
original state and fee coordinates match. Existing raw-route input/output
coordinates receive the existing fee transformation once. Other cases retain
the baseline formula. Changed shared pool facts refresh derived model
parameters; they do not start a whole-plan search. A mixed whole quote is not
assigned to an unrelated productive Market route as training data.

The first model request waits for the existing optional pool catalog load before
enumerating its routes. Otherwise a fresh API process could return an empty
estimate while its known pools were still loading. A failed store load leaves
ordinary estimation available. Model acquisition can still be slow on a cold
process; this correction improves first-request availability, not the baseline
formula or the speed of that acquisition.

Resolved V2/V3 addresses share canonical pool observations and persistence
across seed/catalog aliases. SDK payloads retain coherent caller IDs, while
candidate-private post-state follows the same physical pool even when catalog
metadata arrives between conversions. Hypothetical post-state is never
published as canonical. Compatible same-pool/hash Mainnet coverage merges
during publication, reload and transactional saves. Equal-height replacement
hashes use the existing snapshot path.

The existing immutable Mainnet boundary is unchanged. Sandbox can mutate state
without changing its header: fresh same-header acquisitions still replace
state and old samples remain advisory. The raw RPC LRU remains 4,096 entries
total across block hashes per API process, without a head-change purge or TTL.

When the SDK traverses an empty V3 bitmap word with zero active liquidity,
optional acquisition reads the next 31 directional words in one hash-pinned
Multicall3 batch, clipped to valid tick limits. Demanded reads and successful
coverage survive optional batch failures. The SDK still traverses every word
and initialized tick; no arithmetic jump is introduced. Existing V4 prefetch
and shared-read subscriber cancellation remain in force.

## Internal component ownership

`quoter.route_tools` owns the shared query/feed API; `quoter.custom_routes`
packages generic custom graph/split enumeration from `quoter.discovery`.
`quoter.amm_adapter` owns CyberGold path policy and candidate selection;
`quoter.amm` owns
exact path replay; `quoter.evaluate` owns ordered whole-plan/Core/fee economics;
`quoter.ranking` compares only completed plans. `quoter.funding` and
`quoter.prefix` propose smaller funding, `quoter.policy` supplies optional
bounds, and `quoter.exploration` owns the optional feeds. `quoter.search` owns
the context, ordinary jobs, incumbent, deadline and finalization. Internal
contracts/traces are request-local and never become public quote fields.
Registry owns canonical acquisition and coverage; hypothetical post-state
remains candidate-private. Fast Estimator, SQL store and Transaction
Preparation keep their existing responsibilities; these modules are not new
services.

The unused Uniswap onchain Quoter ABI/config/metadata dependency is retired
from the production pricing path. Retained Node comparison fixtures may use a
test-only oracle. SDK arithmetic remains the pricing implementation; Universal
Router remains execution infrastructure behind the routing adapter.

## Measurements and remaining qualification

Completed searches expose producer time to first whole plan, search duration,
total duration and selection reason. Final canonical verification belongs to
total/finalization time, rather than search duration. Safe operation evidence
distinguishes Quoter search/lookup, Fast Estimator and Transaction Preparation.
Stored quote metrics describe its original search, not the latency of a later
lookup. Client HTTP and browser journey times remain separate.
`metrics.optionalSearch` records the optional start/pruning/repair counts and
the exploratory random seed. Post-selection funding replay belongs to
finalization and cannot qualify an earlier E1 result during ordinary selection.

Focused correctness controls are included in the Python local suite. Native
PostgreSQL controls exercise actual independent connections, concurrent
coverage/whole-record writes and scoped bounds against caller-owned disposable
databases, without RPC. `native_economic_api_processes.py` additionally starts
two independent local Uvicorn API processes and HTTP clients: a process whose
fixture provider cannot acquire a head still retrieves the other process's
original SQL-saved quote, including after a failed explicit Refresh. The
`--actual-sdk` mode additionally uses captured Mainnet state, reduced funding,
successful seeded Refresh and a freshly started process. These correctness
fixtures prove cross-process reuse, not live AMM latency.
The App's paired measurement loop controls database/process cold starts, forced
warm searches, second-process lookups and a header-only advance. The completed
local native-arm64 cohort recorded 180 primary requests, including three failed
requests. Shared candidate lookup took a median 11.2 ms; the baseline searched
again for about five seconds. Cold full searches remained about 6.8–6.9 seconds,
and warm final responses retained the existing five-second comparison window.
These owned-fork results are not production latency guarantees.

Actual receipt checks passed five direct API integration cases, six tiny-USDT
trades and the full 24-journey native MetaMask matrix. The integrated two-browser
case used two real API processes and two actual Swap receipts. Changed-state
preparation kept the selected plan and original accepted bounds. These tests
used freshly deployed Helpers on disposable local forks; the primary quote-only
cohort used the recorded published addresses instead. Their scopes are separate.

The separately retained local implementation report records exact source
identities, model/reference coverage, ordinary failures,
cleanup and the separate evaluation backlog. Cold model availability, estimator
error, selected-plan receipt correctness and route quality are distinct results.
No Mainnet transaction or release follows from this local qualification.
