# Uniswap snapshot worker

Complete CyberGold economic plans are priced by the existing Helpers
`executeExactInput` function through one `eth_call` at `latest`. This applies to
pure Market paths, ordered Core/Market branches and direct basket intents.
Known saved plans skip SDK replay. Candidate construction does not issue an
amount-dependent Core preview: topology and cached configuration are enough to
encode the complete plan, and its single Helpers call supplies Core lots, fees,
residuals and economic output. SDK arithmetic explores new paths, splits and
funding shapes. A reverted optional whole path can still use SDK traversal
to construct a backward-prefix repair; that changed plan is simulated again.

Quotes and execution preparation do not fetch a header or chain ID, nor reread
a block to establish canonicality. Preparation makes a fresh `latest` execution
call with the accepted fees, minimum outputs and actual recipient. Latest
responses have null block number/hash and an explicit `latest` tag. An
`eth_call` response does not contain the header; these responses claim no
verified block identity. Basket/token previews, basket MAX, standalone SDK route
quotes, legacy Core/Market quotation and Helpers gas preflight use the same
latest-read boundary. Explicit historical/pinned callers and background
indexing retain their real-hash contracts.

Quote-only execution uses ephemeral balances and Helpers allowances for one
synthetic payer. Funding adapters cover the configured ETH, WETH, USDC, USDT,
PAXG, XAUt and configured CYGLD inputs. Pool balances, supply, reserve state,
contract code and other accounts are never overridden. Unknown positive input
currencies return the funding adapter's ordinary unsupported-input error;
intermediate currencies require no funding override. Real-wallet funding,
permit signatures and recipient behavior remain the wallet preflight's facts.

Helpers accepts literal Market fees in its execution plan. Buy and residual
conversions are observed with zero output-denominated Market fee; local policy
arithmetic applies that fee to each measured gross output and records the final
plan/net output. This leaves swap inputs and shared-pool execution unchanged.
Sell fees are computed before execution, and the exact routed lot is allocated
input minus that fee. Core fees come from execution. `pricingEvidence` retains
the raw receipt separately from normalized quote amounts; cached observations
and closed log projections retain the pricing and nomination origins.

Identical successful simulations share one observation only within their
owning search, preserving its original observation time and live nomination
origins. Preparation always executes afresh. Changed funding reconstruction
reuses measured conversion debits and only simulates a genuinely changed plan.
Graph walks and normalized topology are also reused within the existing
bootstrap scope. A nearby saved quote retains its complete body and execution
identities; changed allocations are encoded and priced through Helpers.
Successful pool reads and acquired tick coverage are shared within one search,
including custom and external suppliers; candidate post-state stays private.
Later catalog and provider arrivals remain visible.

Core configuration warms at component startup, independently per field. Basket
assets, weights, conversions, recovery identities and fees are kept in memory;
the existing Core/Helpers journal worker applies configuration events and
publishes changes through the existing JSONB store and PostgreSQL notifications.
API processes listen rather than write competing snapshots. Existing protocol
facts/model observations supply optional capacity hints without another Core
read. Cache failures do not reject quotations. Complete saved paths and pure
Market proposals do not wait for Core configuration; direct basket input
identities come from the request. A fresh Helpers execution remains decisive.

Python owns RPC, inventory, event reconciliation and cached observations.
The managed Node 26.10.0 JSONL worker receives raw-unit snapshots, quotes or
simulates ordered branches, and reports missing bitmap/tick coverage to Python.
Candidate post-state is isolated from observed state; branches advance shared
pools in execution order. Wire post-state omits unchanged tick coverage.

Route simulations suspend the SDK swap when required tick or bitmap coverage
is missing. Python acquires that coverage outside the serialized bridge
exchange, then resumes the same request-local calculation. Resumption adds
observed coverage without replacing advanced price, tick or liquidity state.
Cancellation retires owned continuations; losing their worker remains an SDK
error. SDK diagnostics count each start/resume exchange, rather than counting
only fresh swap simulations, and exclude the intervening Python state reads.

AlphaRouter and UniRoute-local discovery children belong to one route search.
They reuse a child after a completed request returns an ordinary supplier error.
Each terminal result or error retires that request's pending quote callbacks and
suppresses later candidate or quote frames from its calculation. This keeps an
ordinary discovery error from repeatedly paying Node/module startup cost.
Cancellation, canonical-state disproof and broken framing or transport still
retire and reap the child. Supplier errors retain their existing public outcome;
worker reuse does not change the selection clock, pricing slots or economic
ranking. AlphaRouter receives the existing chain-31338 fork dependencies while
keeping the actual execution-chain identity. Hosted tools nominate shared
Mainnet market segments for this fork, then compose the local Core anchor;
they are not asked to quote the fork-only CYGLD contract on Mainnet. Logs retain
both execution and nomination chain identities. Raw AlphaRouter topologies are
published before deep quote callbacks finish, and independent UniRoute-local
queries can proceed while another query awaits pricing.

New ordered AMM explorations acquire their missing initial pool snapshots
concurrently. Replay consumes those observations in hop order and preserves the
candidate's private post-state. Each distinct concentrated pool's first bitmap
word starts after its snapshot, concurrently with sibling pools. Later bitmap
words and initialized tick rows still follow exact SDK demand. Ordinary
prefetch errors fall back to required reads; subscriptions are owned and drained.
Unbound latest state and tick coverage stay outside persistent canonical banks,
event advancement and completed cross-request getter caches. Token display
metadata does not block raw-unit pricing; required concentrated-pool spacing is
read only when SDK exploration needs it. Exploratory state
disproof affects its own construction/provider, not independently completed
Helpers observations. SDK-head bounds no longer reject latest-priced candidates.

Saved complete plans start while ordinary Core basket/path preparation runs
independently. Exact/nearby SQL lookups, catalog preparation, custom discovery
and external suppliers start independently; an optional slow lookup does not
extend the selection window. Cache writes belong to the component and do not
delay the response. Optional-path errors do not suppress a later retry or an
independent successful candidate, and there is no sixteen-attempt ceiling.
These changes retain the existing selection clock, pricing capacity and
comparator. The structured SDK
engine and completion-driven scheduler remain shared by V2, V3, V4, mixed and
split exploration, retained-route construction and caller-selected V3 paths.
Python extends concentrated-liquidity coverage as needed within the producer
deadline; private pool state advances in actual swap order.
Cold exact-output redemption can
freshly price and qualify a complete initial seed before unrelated candidates
refill the released pricing slots. Its seed estimate alone never establishes
execution terms. Native Core wrapping, adapter encoding, Helpers validation and
the existing five-second search/fifteen-second maximum selection window retain
their established behavior.

Hosted UniRoute API and Guidestar requests share a dedicated
`UniswapApiQueue` owned by the runtime's quote engine. It persists across
searches and paces HTTP starts in FIFO order, releasing its lock before network
work so responses can overlap. It is separate from the chain RPC broker. The
default is six starts/second, matching the documented Uniswap default; optional
`CYBERGOLD_UNISWAP_API_RPS` selects the quota assigned to the configured key.
See the official [rate limits](https://developers.uniswap.org/docs/trading/swapping-api/common-errors#rate-limits).

HTTP 429 pauses the shared queue using `Retry-After` seconds or an HTTP date
(one second when absent/invalid), then retries through the same queue. Other
HTTP errors return normally. Waiting and retries use the existing quote task's
deadline and cancellation; local route tools continue independently. There is
no extra quote gate, retry-count cap or time budget. Cancellation removes
queued work without counting it as an HTTP attempt. Runtime shutdown cancels
waiting tasks; closing an individual search provider leaves the shared queue
intact.

`metrics.routeDiscovery.apiRequests` records aggregate and per-provider
`httpStatuses`, `queueEntries`, `queueCancelled`, `summedQueueWaitMs` and
`retries`, alongside existing HTTP attempt/completion/error/cancellation times.
Queue entries include immediate admissions and retries; `retries` counts only
retry HTTP attempts that actually start. A 429 is an error attempt even if its
retry succeeds. Transport failures have no invented HTTP status. Status counts
describe HTTP responses, independently of later topology parsing. Queue time is
separate from HTTP elapsed time. These fields survive the existing economic
log projection and stored-quote evidence; cached counters describe the original
search. Credentials, headers, response bodies and exception text are excluded.

This is one process's configured-key budget. Multiple processes, blue/green
instances or other applications sharing the key need to share the assigned
quota between their configured rates; this queue does not coordinate across
hosts. A shared-key external consumer may still cause 429, handled as above.

The existing registry worker also retains pool activity in the existing
`cybergold_uniswap_state` JSONB store. Normal monitoring reuses the canonical
logs and header checks already acquired for state maintenance; quote/model
acquisition never loads or writes activity. Known CYGLD and active connector
pools are monitored at the existing worker cadence, independently of monthly
catalog discovery. A persistence outage leaves observations/quotes available
and retries the activity bundle on the next worker run. Missing durable history
is caught up only in bounded worker ranges, without rescanning an acquired
suffix or issuing RPC work from an HTTP request.

`GET /api/activity/pools` follows the existing activity bearer, GET/HEAD,
no-store and unavailable-error conventions. Optional protocol, PoolId,
PoolManager or pool-address filters select persisted records. V4 identity
contains both PoolManager and PoolId, not a singleton token balance. Each pool
retains at most 1000 recent events and 64 scan-range rollups; the public response
returns the latest 100 events across selected pools. Start/end blocks, canonical
end hashes, retention limits and truncation are explicit. Coverage begins at
the worker's first observed baseline, not pool creation. This API reports mined
history at observed-block cadence, not instant finality or mempool activity.

Bundles commit events and their range checkpoint together. Restart resumes
that checkpoint; a changed canonical hash removes orphaned ranges, events and
rollups before bounded replay. If a reorg predates the retained baseline,
coverage restarts at the observed block. Catalog rollback removes activity for
the orphaned protocol/pool identity; Sandbox generation namespaces isolate fork
histories. Unknown/malformed supported layouts retain raw topics/data with null
arguments and no fabricated volume.

Rollups keep token0/token1 raw input/output volumes separate. V3 swap amounts
are pool deltas (positive input); V4 amounts are caller deltas (negative input).
V4's emitted swap fee is its executed combined fee, not stored LP fee. Liquidity
changes remain range-liquidity units; V4 events provide no deposited token
amounts. V3 Burn can credit owed principal before Collect, and a zero Burn is
not a liquidity removal. Sync is a state update, not additional swap volume.
The bounded rollups make no USD, per-pool TVL or all-time volume claim.

SDK core/V2/V3/V4/router packages provide token identities, integer swap math,
PoolKey and branch composition. The public concentrated `v3Swap` engine uses
explicit spacing and V4 directional effective fees. V4 PoolKey retains its
original fee. SDK positive amounts mean input and negative amounts mean output;
V4 core's sign is opposite. A minimal install patch exposes the existing SDK
remaining-amount return property without changing the swap loop.

The root Dockerfile ships Node and SDK packages with Python; the Python-only
subdirectory Dockerfile remains a historical comparison artifact. No B2B image
adoption is claimed from local IPC tests. The owner runs all B2B commands.

`npm run test:sdk` covers rounding/differential state, directional V4 fees,
missing coverage, underfill at limits, ordered shared pools, malformed framing
and cancellation. The native Python suite covers fees/compilation/cache/API.

Cold catalog acquisition for the canonical Mainnet V2 factory, V3 factory and
V4 PoolManager starts at their inclusive deployment blocks: 10,000,835,
12,369,621 and 21,688,329. The existing chain-31338 Sandbox inherits those
Mainnet histories. Only those exact configured deployments in these two
profiles use the defaults; another chain or producer address starts at genesis.
Persisted cursors/checkpoints continue literally, including a cursor earlier
than the default. This retains pool initialization before CYGLD deployment and
adds no runtime identity probe or pool/quote eligibility rule.

V4 PAXG connectors use a separate `v4-paxg` discovery cursor and canonical
rewind checkpoints, starting at the same configured PoolManager birth. Core
pool discovery cannot stand in for historical PAXG discovery. Cold Market
requests can quote bounded common hookless V4 PoolKey candidates through
StateView and the SDK while the background catalog catches up custom keys.
An initialized key is retained with its acquisition block/hash; missing or
uninitialized keys remain ordinary unavailable candidates, with no claim that
all V4 pools or all of one pool's tick domain have been acquired.

The floors were verified against the deployment receipts and pinned official
[V2](https://raw.githubusercontent.com/Uniswap/v2-subgraph/3d7c06982866e0535a350ee15c792b4003231b2b/config/ethereum/config.json),
[V3](https://raw.githubusercontent.com/Uniswap/v3-subgraph/b4a0e8d34b8238482cadd3929ae88d3426a7067b/config/ethereum/config.json)
and [V4](https://raw.githubusercontent.com/Uniswap/v4-subgraph/0c13ab2fbd95306272528ed781511d7e2aa338d3/networks.json)
subgraph records. The V2 config conservatively starts one block before the
actual successful creation receipt. Mainnet creation transactions are
`0xc31d7e7e85cab1d38ce1b8ac17e821ccd47dbde00f9d57f2bd8613bff9428396`,
`0x1e20cd6d47d7021ae7e437792823517eeadd835df09dde17ab45afd7a5df4603`
and `0x747e0e02b7590eed32cface28e83260884e0b80675f5ae223c6888053aa68528`,
respectively.

Upstream contract packages were published with Solidity build tools in runtime
dependencies. `vendor/uniswap-abi-packages` preserves their published files and
removes installation of unused Solidity/build dependencies from local manifests.
The SDK mathematics packages stay pinned. Original tarball integrity and package
manifest content are recorded; independent comparison confirms unchanged ABIs.
The production Dockerfile copies these directories alongside their npm links.
A compatible OpenZeppelin 4.9.6 npm override removes an unused source-package
advisory; it changes no Helpers Solidity pin or deployed/router bytecode.

The initial production npm audit found 38 advisories. Ordinary transitive fixes
left 33; ABI-only dependency packaging leaves 19 low and no moderate/high/critical
advisories, preserving the existing high-severity CI check. Low Ethers elliptic
advisories remain; the worker does not sign or hold wallet keys. Record the
independent risk assessment rather than treating absence of high alerts as a
complete security audit. Never silently downgrade selected SDKs via audit-force.
