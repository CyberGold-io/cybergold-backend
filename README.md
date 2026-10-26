# CyberGold backend

Product API and indexer worker, extracted from `cybergold-app`.
Both installed environments now use Python/FastAPI, Web3.py and psycopg after
H24; the root Dockerfile builds the API/worker image. Retained TypeScript/Viem
source remains the comparison reference during the observation period.
The frontend remains Next.js. New images use native Python API/worker commands;
Ops keeps the established launch commands for retained images. The earlier
Node-command translation shim and Node production entry modules are removed.
TypeScript HTTP/domain fixtures remain a local comparison reference, not a
production runtime. `npm run start:api` / `start:worker` run the local Python
virtual environment with private environment inputs. This repository owns the current
server routes, PostgreSQL domain code, live recovery reader, market caches and
worker controls; browser wallet signing and submission stay in the frontend.

RPC-dependent errors retain their existing error text, code and correlation ID.
An optional `diagnostics` object preserves observed RPC method, operation stage,
elapsed time, upstream error code or HTTP status, sanitized provider message,
and failure type when available. It distinguishes provider timeouts from the
Backend's operation deadline. Public JSON errors, quote-stream terminal errors
and route failures share this additive contract; request logs retain the same
context and correlation ID. Provider URLs, RPC parameters and authorization
values are excluded. Existing deadlines, retries and product messages are
unchanged; these fields add no frontend warning or required client behavior.

Product responses expose `X-CyberGold-Request-Id`; callers may send the optional
UUID `X-CyberGold-Attempt-Id` to join one logical browser trade across its reads.
Missing or malformed attempt metadata is ignored. Intent, market and unified
trade stream frames retain their own request reference, and failures add a
correlation ID matching a best-effort JSON log. Losing-provider failures remain
observable when another provider succeeds. Coalesced quote work has a separate
`workId`: subscribers share that producer identity and retain distinct request
and attempt IDs. The IDs never affect sharing keys, signing, authentication or
product decisions. Browser diagnostic POSTs keep the supplied operation's
`requestId` and record their own ingress ID as `diagnosticRequestId`.

The optional `X-CyberGold-Backend-Revision` response header records the responding
process's build commit when `CYBERGOLD_BACKEND_COMMIT` supplies a 40-hex revision.
It is absent for local builds without a commit and never required for a request.

`cybergold_backend_quote_outcomes_total` counts semantic subscription outcomes
separately from HTTP status (a quote stream may fail under HTTP 200).
`quote_first_executable_seconds` measures the first qualified/complete quote,
excluding indicative model/estimate frames. `quote_stage_events_total` and
`quote_provider_outcomes_total` retain bounded stage/strategy observations.
These count logical HTTP subscriptions, not physical shared RPC producers.
IDs, addresses, amounts and exception text remain outside metric labels.
Helpers simulation/estimation failures preserve the transport's sanitized
RPC context and expose an EVM selector plus a recognized error name when its
arguments decode; encoded return arguments and signed material are excluded.

`GET /api/account/wallet-balances?holder=0x…` is a focused Python read operation
for the Apps' configured CYGLD Core and fixed XAUT/PAXG/USDT/USDC/WETH assets,
plus native ETH in one Multicall3 `aggregate3` call at
`0xca11bde05977b3631167028862be2a173976ca11`. The six ERC20 `balanceOf(holder)`
members and `getEthBalance(holder)` against Multicall3 itself all allow individual
failure. There is one hash-pinned balance `eth_call`, with no separate native
balance RPC or fallback calls. Wallet display and swap reads both use this batch.
It returns raw integer balances as decimal strings, their
selected block/hash/chain context and explicit per-asset failures. The caller
selects its wallet, not a token, ABI or provider. No wallet result is written
to PostgreSQL or shared between holders; HTTP is `no-store`. Signing and
submission remain browser-owned. The existing serving deadline/cancellation
applies. `purpose=display` opts ordinary loading into reading the latest block
once, then all seven balances through the aggregate at that exact EIP-1898 hash
with `requireCanonical: true`. It omits
the repeated chain-ID check and final block reread (two RPC requests instead
of four). Unmarked, `purpose=swap-preflight` and other requests retain both
existing checks. Older Apps and already-open tabs keep their original behavior;
older backends ignore the extra parameter, so either update order is compatible.
Viem/Web3 comparisons and the native Linux fixture exercise concurrent
wallet isolation, wide values, partial failures, reorg/outage and cancellation.

`GET /api/account/token-balance?holder=0x…&tokenId=cygld` remains a compatibility
operation for earlier clients reading one wallet asset independently.
`tokenId` selects `eth`, `cygld`, `xaut`,
`paxg`, `usdt`, `usdc` or `weth` from the existing fixed assets; it cannot select
a contract or provider. Each response carries its own canonical block context
and the existing balance success/failure union. A slow or failed asset does not
hold another asset's result. The fifteen-second deadline, disconnect cancellation
and no-store apply to each request. Current product wallet display and swap reads
use `wallet-balances`; separate compatibility snapshots can come from different
blocks and do not replace the shared transaction snapshot.

`GET /api/governance/core-facts` also observes Core's `safeWallet` at the same
canonical block as its seven existing governance configuration fields. This is
the configured Core address, not a caller-selected authority. Its field failure
remains unavailable; it does not fabricate an address or change Safe ownership.
The additive HTTP field is optional for retained responses from the earlier API.

`GET /api/account/liquidity-positions?holder=0x…` returns the wallet's Uniswap v4
NFT positions for the fixed Ethereum PAXG/CYGLD pool. Incoming and outgoing
PositionManager Transfer logs since pool initialization establish ownership;
the NFT's complete PoolKey selects this pool. Contract reads share one canonical
block hash. Each position and the aggregate expose deposited PAXG/CYGLD token
quantities as exact decimal strings, including unclaimed LP fees. StateView
reads the position under PositionManager with its NFT tokenId as salt, supplying
liquidity and the last collected Q128 fee growth. The current inside-range growth
adds fees with Uniswap's uint256 wraparound and integer rounding. A fee-read
failure makes the total unavailable rather than publishing principal alone.
Previously credited fees are not counted again; v4 position state has no separate
cached tokens-owed balance. Empty NFTs
remain in the position count. Supplier failures return unavailable. A Sandbox
snapshot before pool initialization naturally has no positions in this pool.
The existing disconnect cancellation and
no-store response apply; complete LP discovery has a sixty-second deadline.
A zero PositionManager NFT balance avoids historical scanning. Other wallets
scan recent Transfer chunks backward until their current NFT count is fully
accounted for, or until this pool's initialization is reached. No wallet state is
persisted. Sandbox uses its
configured fork RPC; external Uniswap links belong to Ethereum Mainnet.

`GET /api/governance/helpers-facts` returns the configured Helpers fee, Permit2,
wrapped native token, owner, approved adapters and pause state at one canonical
block. Each read retains its own success/failure; a failed allowlist is unknown,
not an empty list. Only the configured Helpers contract is queried, with the
existing fifteen-second operation deadline and cancellation. There is no
caller-selected contract, ABI or RPC provider and no database write.

`GET /api/governance/safe-principal?address=0x…` observes a governance
principal's bytecode, Safe owners and threshold at one canonical block. It
returns per-read failures and a decimal-string threshold. The App keeps its
existing EOA/Safe compatibility and authority interpretation; this API grants
no permission. The caller selects a principal, never an ABI, method or provider.
There is no database write, nonce/simulation, signing or submission. The existing
operation deadline and disconnect cancellation apply.

Run the current API/worker with the locked Python environment:

```sh
uv sync --project python-candidate --frozen
PYTHONPATH=python-candidate/src uv run --project python-candidate --frozen python -m cybergold_candidate.main
# Separate worker process:
PYTHONPATH=python-candidate/src uv run --project python-candidate --frozen python -m cybergold_candidate.worker_main
```

Provide each process's private configuration through its environment; neither
process loads a private `.env` implicitly. The API defaults to port 3000 and
worker to 3001; set `HOST`/`PORT` for the placement. The worker exposes indexing
controls on its private listener; Ops owns scheduled reconciliation, generation
recovery and blue/green handover. API requests do not start reconciliation.

Retained TypeScript/Viem code is a migration comparison reference. Its canonical
checks use Node 26.10.0, `npm ci` and `npm run ci-check`. The Python comparison
suite is `bash python-candidate/tests/check-local.sh`; native container/DB
rehearsals exercise the actual Python serving image and persistence libraries.
The latest [assembled read qualification](python-candidate/remaining-reads-qualification.json)
includes all sixteen operation deadlines, caller disconnect and exit-zero
shutdown, with synthetic RPC only. New images expose the native Python runtime
label and commands; Ops retains the proven legacy commands for historical images.
The Uniswap market candidate additionally ships an isolated Node 26 SDK worker
for snapshot arithmetic. Python keeps RPC, indexing and cache ownership; see
[the worker and dependency notes](docs/uniswap-sdk-runtime.md). This source
change does not identify an installed image.

Remote API entry is authenticated at the stable Ops Nginx ingress:
`https://api.sandbox.cybergold.io` and `https://api.app.cybergold.io`, each with
its own bearer. That boundary covers every API operation, including the faucet,
and survives backend image rollback. This process retains its private listener;
do not publish it directly to the Internet. Local or deployed Next.js servers
hold any remote-entry credential privately. The existing private App-to-backend
connection uses its network boundary and does not need that remote-entry token.

The current Sandbox faucet does not check Origin. Remote callers use the same
API bearer as other backend operations; there is no second faucet credential
for frontend developers. Its existing enabled setting, funding-service token,
request ID, trusted client IP and funding limits remain in place. The isolated
funding-service token is internal, unrelated to the remote API bearer. Worker
controls still use their own listener and worker credential; they are not
exposed by either dedicated API hostname. The public App facade remains public.

Supply configuration through the environment; `.env.example` describes local
defaults. The established profile names are retained during extraction.
API/worker settings are environment inputs; use the private configuration
launcher for the chosen process. The retained Node comparison fixtures use
Node's explicit `--env-file` with their synthetic test environment.

Successful `dev` CI selects the **Sandbox** backend package; successful `main`
CI selects the separate **Mainnet** package. Each environment has its own
blue/green containers, data/configuration, desired reference and release
state. Its API and worker use one backend image digest. Publishing, installation
and observed acceptance are separate steps under the existing Ops controller.

`contracts/extraction-baseline.json` records the original source files and
hashes. Logical indexer/schema versions and advisory lock identities are
preserved; a changed source hash does not require resetting an existing DB.
`contracts/abi-source.json` records each selected Core and Governance ABI's
Protocol artifact path and producer commit. The generator reads the bundled
`contracts/release-abi/*.json` files; a sibling Protocol checkout is not needed.
`node scripts/generate-contract-abis.mjs --check` verifies the generated modules
against those selected files. For a contract release, update only the selected
artifact and its producer record, then run the same command without `--check`
to regenerate. `node scripts/snapshot-source-identity.mjs`
prints the source-binding digest used in backend image labels and Ops snapshots.
`tests/contracts/private-next-baseline.json` captures 64 real HTTP responses
from the production Next build at the extraction commit, compared with the
built backend worker on loopback. It covers missing/short/configured worker
credentials, incorrect bearer schemes, malformed/oversized bodies and both
private routes, including diagnostic responses. Tokens in this fixture are
public test strings. No database or external RPC was configured; successful
indexing/generation behavior is qualified separately in the Ops fork evidence.
`npm test` replays the recorded status, response bytes and relevant headers
through Fastify, alongside the existing public API fixtures.

The market cache replaces Next fetch revalidation with standard process TTL
and coalescing, retaining the successful observation's original timestamp.

The canonical implementation plan, progress checkboxes and owner-executed B2B
handoffs are maintained in `cybergold-ops/docs/work/in-progress/` under
`app-ops-focused-read-apis-implementation-plan.md` and
`app-ops-backend-split-operator-handoff.md`. Python, database relocation,
and Valkey remain separate planned migrations. Centralized operational
observability is installed and follows its own branch-driven delivery.

### Backend operational metrics

The API and worker each expose `GET /metrics` on their existing private listener.
B2B publishes API `/metrics` and worker `/metrics/worker` through the target's
existing authenticated API hostname and bearer. The exact worker metrics route
cannot invoke worker controls. The public Next.js App does not proxy these paths.

The official [Prometheus Node client](https://github.com/prometheus/client_js)
exports in-memory counters, histograms and observations. Scrapes perform no
DB/RPC work. Metrics recording or collection failures leave product handlers
usable; no collector connection or new readiness prerequisite is introduced.

- HTTP counters and duration histograms use fixed routes, bounded methods and
  status codes; unknown paths become `unmatched`. Scrapes are excluded.
- Gold/FX counters distinguish hits, expiry/misses, coalesced callers, validated
  refreshes and fallback. Acquisition timestamps do not advance on cache hits.
- RPC proxy counters count individual HTTP attempts, including retries, and
  transport failures. HTTP 200 can contain a JSON-RPC error. Timing ends at
  response headers, excluding pacing and body parsing; these are not counters
  for every Safe/indexer upstream request.
- Worker reconcile outcomes and dashboard history lag use existing returned
  progress. Lag is relative to the head observed during that run, accompanied
  by its observation timestamp. Missing progress stays absent. This is not a
  live head measurement or complete per-Safe-stream lag.

Values reset when a process/slot is replaced. Identifiers, request URLs, tokens,
wallets, bodies and exception text are never metric labels. Prometheus provides
persistent history; Grafana's **CyberGold backend** dashboard explains each
measurement. Rollout is tracked in Ops' U4/H10 handoff.

### DApp diagnostics and Core activity

`POST /api/diagnostics` accepts best-effort browser observations through the
existing API entry bearer. The Next.js adapter holds that credential privately.
The API projects operation, outcome, reason, flow mode, timing, asset count,
ephemeral attempt/quote UUIDs and a submitted transaction hash onto its standard
JSON log. Optional error observations retain only a signed safe integer wallet/RPC
code and a four-byte EVM selector; invalid optional fields are ignored. It drops
all other fields, including error text, encoded arguments, wallet addresses,
signatures and raw RPC bodies. It uses Fastify's normal JSON parser and default
body limit. `202` acknowledges receipt, not delivery to Loki. Browser reports
are untrusted observations, not chain evidence, user counts or audit records.

`GET /api/activity/core` reads the latest 100 Core logs from the existing raw
journal, using a read-only consistent database snapshot. It includes journal
coverage, block/transaction identities and decoded public event arguments.
The shipped Core ABI plus the historical migration events at Protocol
`1b7652c68c8ba8974a7e8320e2910e2a7db14a19` decode the retained September 28
upgrade receipt. Unknown versions remain visible with a topic and null decoded
fields. The view performs no RPC calls, schema changes, event writes or dashboard
cursor resets. Reorg deletion in the existing journal is reflected on the next
read. It does not extend Helpers/Safe indexing or enumerate reverted/no-event
transactions; `hasMore` explicitly identifies a truncated recent view.

Unit/HTTP checks run in `npm run ci-check`. The additional PostgreSQL fixture is
`node --env-file=tests/fixture.env --import tsx tests/integration/core-activity.ts`,
with `DATABASE_URL` pointing to a disposable empty local database. Never run that
fixture against a product database.

### Protocol activity and reserves in Grafana

`GET /api/activity/safe` is the corresponding operator view across the existing
configured Safes. It reads up to 100 retained journal logs and uses the indexer's
existing indexed and non-indexed `ExecutionSuccess`/`ExecutionFailure` layouts.
Unknown or malformed versions stay visible with null execution fields. Each
Safe's stored journal bounds and execution-projection cursor are returned, along
with the current projection lookback. Older retained executions are visible
without widening that lookback, resetting the projection or making RPC calls.
This is a recent bounded view, not complete lifetime history. Pending proposals,
confirmations and wallet attempts belong to their existing service/diagnostics.
The environment bearer protects this API; no public frontend adapter is added.
Its disposable database fixture is `tests/integration/safe-activity.ts`, run
with the same local PostgreSQL setup as the Core fixture above.

After a successful worker reconciliation, a best-effort asynchronous read copies
committed dashboard and Core-journal observations into `cybergold_protocol_*`
gauges. Existing authenticated worker scrapes collect them; scrapes never query
Postgres or RPC. Failed reads retain the previous timestamp and expose
`read_success=0`. A restart leaves values absent until the next reconciliation.
Supply, net issuance and reserve quantities use product token units. Snapshot
chain age is distinct from collection age. Reserve balances are not executable
DEX liquidity; Core event counts describe the latest 100 retained logs, not
lifetime totals or a time-window rate. These observations do not activate the
separate protocol-invariant monitor.

## Python migration source and release

The [candidate implementation/qualification](python-candidate/README.md) preserves
the complete existing API, schema and Ops-triggered worker. Its two executable
modules are `cybergold_candidate.main` and `cybergold_candidate.worker_main`.
New images use these native module commands directly. Ops selects commands
from the canonical image runtime label; retained Node and earlier Python bridge
images keep their established commands for rollback.

The draft feature does not publish a desired image. H24 merges it to `dev` for
ordinary Sandbox release, observes retained Node rollback against current data,
then promotes the unchanged tree to `main` for Mainnet. No database relocation,
new required CI job, browser API change or permanent TypeScript RPC shim is added.
Remove retained build/reference scaffolding only after installed observation.

### Focused protocol facts — additive U5 feature

`GET /api/protocol/facts` reads the configured Core/Helpers basket, reference, fees, pause state and current issuance capacity at one live canonical block hash. Optional `issuanceCapacity` provides `totalSupply`, `maxTotalSupply` and `effectiveCygldSupplyCap` immediately, including on a cold process with no quote-model history. Raw values are decimal strings; metadata and individual contract failures retain their own disposition. It performs no database reconciliation and accepts no caller-selected ABI/provider/target. The optional existing Helpers profile value does not add a global startup prerequisite. Responses are `no-store`; the frontend retains query reuse. This feature follows H24 as a separate backend-capability/frontend-consumer release.

The [native/API and generated-contract evidence](python-candidate/protocol-facts-qualification.json) is recorded separately from the U1 migration receipt; that historical receipt binds base commit `68d6b76`. No installed facts endpoint or browser-RPC retirement is claimed by this feature.

### Optional gold/FX shared reuse — U3

`CYBERGOLD_MARKET_CACHE_URL` enables the standard pinned Valkey async client.
Unset keeps existing local behavior. The optional service is lazy; cache failures
preserve local coalescing and the existing ten-second supplier/fallback policy.
Keys separate configured chains and feeds; representations carry their original
acquisition expiry. A hit never restarts a full local TTL or rewrites last-known
age. Failed/stale supplier outcomes are never cached as fresh observations.

Gold refreshes after 30 minutes. A failed refresh retains the last successful
price and acquisition timestamp until the one-hour warning threshold; an initial
synthetic fallback remains estimated immediately. Previously cached one-hour
records obey the current acquisition lifetime without a cache flush. FX remains
on its existing five-minute policy.

[Native qualification](python-candidate/shared-market-qualification.json) compares
two real API processes: baseline two supplier requests per feed, shared warm reuse
one per feed; twenty callers during cache failure still request the supplier once.
The four-key working set is approximately 1 MiB including Valkey overhead. Ops
selects 32 MiB allkeys-LRU with a 96 MiB container envelope, no persistence, one
private instance per environment shared by API colors. Native pressure eviction,
expiry, stale fallback and exit-0 shutdown are covered. Simultaneous cold processes
can still duplicate a bounded supplier request; no distributed lease is introduced.
This follows H25 as a separate H26 release; historical U1/U5 receipts retain their
own source/image identities. It does not remediate pool-observation authority.

Pinned client [valkey-py](https://github.com/valkey-io/valkey-py/releases/) 6.1.1
and upstream [Valkey](https://valkey.io/download/) 9.1.2 use standard protocols,
connection pooling and allkeys-LRU; no custom cache server or scheduler is added.

### Authoritative Uniswap observations — U3/U5 B1

`POST /api/pools/snapshot` accepts token addresses and a uint24 fee. The configured
factory supplies the pool address; slot0, active liquidity and both token balances
are read at the same canonical block hash. Wide values remain decimal strings.
The operation retains a fifteen-second deadline and cancels on caller disconnect.
No caller-selected provider, factory, pool, ABI or observed state reaches RPC.

The existing `/api/quote-pool-cache` envelopes remain available for older frontends.
Only identifiers from new submissions or retained rows reach the producer. Reads
refresh all derived fields; writes completely replace them, including an empty
factory result. Browser quote-success hints are discarded. RPC failure does not
publish historical observations or write a new one. The existing database schema
and per-row commit behavior are unchanged; this is not a database relocation.

[Native qualification](python-candidate/pool-producer-qualification.json) covers
actual Web3/viem wire encoding, five canonical calls, wide values, fabricated new
and retained Postgres data, full replacement, supplier failure/recovery, reorgs,
cancellation and exit-0 shutdown. The optional comparison suite includes producer
fixtures; the retained Node implementation is a historical reference, not this
release's authority. This slice does not move quote arithmetic, Helpers previews,
wallet signing or receipts. No shared on-chain cache or distributed lease is added.
Its frontend uses a five-second TanStack query to share discovery and liquidity.
H27 installs backend capability before consumers. Installed remediation and its
retained pair must be observed before closing the pool-authority finding.
### Sandbox fork state in the browser

The existing `GET /api/dashboard/onchain-summary` adds the optional
`sandboxForkGeneration` field for chain 31338. It reads the durable anchor
written by the existing fork refresh and worker; it introduces no RPC request,
database write, schema change or new API route. A missing anchor returns null;
Mainnet has no field. Retained backends without the field remain compatible.

The App uses a changed generation to discard old Sandbox pending transactions,
receipt queries and local Safe execution records, even when the Safe nonce is
unchanged. Current wallet connections and Mainnet records remain. This is a
routine source release through the existing Sandbox pipeline, with [native qualification](python-candidate/fork-generation-qualification.json);
installed next-refresh browser acceptance is recorded by Ops.

## Focused basket previews

The [unified trading coordinator](docs/unified-trading.md) exposes one
`/api/quotes/trade/stream` intent and `/api/quotes/trade/model` for Backend-selected
complete Core or supported market executions. Quotes compare fee-inclusive
amounts, preserve explicit retained execution and keep wallet signing separate.
Existing family-specific APIs remain compatible with older clients.

`POST /api/quotes/basket-preview` serves the four existing Helpers basket issue
and redeem previews used by Swap. Each request names a product mode and raw
amounts; each response contains the canonical block identity, configured Helpers
address and the unchanged preview tuple. JSON amounts are decimal strings and
token/basket ordering is preserved. The shipped ABI performs ordinary encoding
validation. The route uses the existing private backend bearer ingress and
15-second read deadline, with caller cancellation, redacted correlated errors
and no-store responses. It accepts no caller-selected contract/provider/ABI.

`POST /api/quotes/basket-max` accepts `driverToken` and a wallet-limited
`maximumAmountsIn` vector in configured Core asset order. It returns the largest
raw proportional driver and canonical budget vector whose unclipped canonical
Core gross issuance fits remaining supply capacity, bounded by every supplied
wallet amount. Weights, decimals, conversions, fees and capacity use the existing
canonical block read contract; one Helpers exact-in preview validates any
positive result and supplies the recipient net. Zero capacity or insufficient
wallet budget returns zero amounts. Integer fee plateaus and token rounding are
preserved. The endpoint does not read a wallet or add a Market basket provider;
the ordinary exact-in preview remains authoritative when the App quotes the
returned amounts.

[Source and native qualification](python-candidate/basket-preview-qualification.json)
compares actual Viem calldata/results for all four modes and the assembled Linux
API against a synthetic authenticated provider. This read-only slice has no
worker, database, cache or wallet-submission effect. The retained JSON-RPC route
and wallet RPC endpoints remain available.

## Contributing and license

See [CONTRIBUTING.md](CONTRIBUTING.md) for public fork setup, local validation
and the feature-to-`dev` contribution path. The project license is
**AGPL-3.0-only**; [LICENSE](LICENSE) contains the full text.
[Licensing scope](LICENSING.md) preserves existing MIT and other third-party
notices and explains corresponding-source obligations.

## Dependency security

The owner-approved [dependency security policy](DEPENDENCY_SECURITY.md) requires
PRs to pass `dependency-security` for every unaccepted finding, including
development and transitive dependencies. Remediate through CyberGold-maintained
parents; any risk exception needs a specific owner decision. See the policy for
current GitHub plan limits and local validation.
