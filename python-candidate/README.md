# Python API and worker

The Python API/direct-mode worker is the serving implementation accepted in H24.
The TypeScript/Viem source remains the behavioral comparison reference. The root
Dockerfile builds Python; the candidate Dockerfile below supports isolated local
qualification. Further source changes do not relocate a database or add a
required CI job. Installed acceptance is recorded in Ops' linked workplan.

The locked Python 3.13.14 candidate uses FastAPI/Pydantic/Uvicorn, HTTPX,
cachetools, Web3.py, psycopg and the official Prometheus Python client. The Docker base and dependency hashes are pinned.
Existing setting names, PostgreSQL schema version 12, table/model keys and
semantic cursor versions are preserved. The October 5 legacy recovery retirement
below supersedes the historical legacy-row/Node rollback comparisons.
Activity/dashboard reads never initialize the schema. Pool-cache requests
retain their existing schema bootstrap; worker initialization remains separate.
Database connections are lazy.

Core, Market, route search and caller-selected Uniswap quotes use one forward
structured route model, `RouteQuoteEngine`, candidate scheduler and execution
compiler. Original direct/via-WETH V3 skeletons can quote before optional pool
discovery finishes. Each completed candidate can enter the owning producer's
qualification while exploration continues; no full V3 wave precedes other
routes. Pool-state simulation uses the installed Uniswap SDKs, with native
Quoter pricing inside the same engine when required state is unavailable.
Retained-plan checks and advisory history use that same route identity.

Packed V3 input is normalized at API/retained-input boundaries. HTTP V3 path
projections and the deployed adapter ABI are produced at their output
boundaries. The compiler preserves Core's whole-path V3 execution and historical
V3-only deployments, alongside the existing typed multi-protocol adapter;
this source refactor changes no Solidity deployment. Core basket fees, asset
order, shared-pool state replay, bounds and Helpers validation stay with Core.
Market keeps its own fee and settlement economics over the shared engine.

The existing producer owns selection time: search through five seconds, extend
to fifteen only when none qualifies, then finish canonical validation and drain.
Route/intent `rpcReadsScope: "coordinator"` marks their coordinator counters;
they do not include every engine observation or supplier request. Candidate
calls now count common-engine jobs rather than only the old V3 batch members.
These counters alone cannot establish RPC savings. Smart Order Router/AlphaRouter
is deferred until this pipeline provides a measured comparison baseline.

Implemented and compared with the **actual retained Node implementation**:

- Gold/FX strict provider/payload validation, timestamps, fallback and acquisition
  age: 150 cases. HTTP bodies, status, content type, cache headers, supplier call
  counts and HEAD responses: 14 cases. Standard process caching shares refreshes,
  preserves the fixed lifetime, retries uncached fallback and cleans up on shutdown.
- RPC policy: 72 cases. The `/api/rpc` HTTP route: 34 cases including raw response
  bytes, ID/error precedence, body limits, unsupported methods, supplier failures
  and deadlines. The existing public Sandbox RPC pacing, cooldown and one 429
  retry are preserved; caller disconnect cancels the upstream call. No implicit
  HTTP/Web3 retries or provider caching are enabled.
- Safe execution ABI: 26 cases. Core/historical activity ABI: 43 cases including
  tuples, wide integers, checksum addresses, empty arguments and unknown records.
- PostgreSQL readers: 14 view comparisons covering Core/Safe history, dashboard
  snapshots, pool-cache chain/pair/age ordering and editor-scoped aliases. Activity
  reads use repeatable read-only transactions; unknown rows stay visible.
- Pool-cache HTTP/writes: 42 comparisons preserve validation, lookup/record
  responses, reversed-pair deduplication and observation merge/SQL bindings.
  Native PostgreSQL writes match Node and remain readable by retained Node code.
  Existing browser-authoritative observation behavior is preserved for this port;
  its separate U3/U5 remediation is not closed by migration.
- Safe service HTTP adapter: 85 comparisons cover all six actions, request/body
  forwarding, valid/invalid supplier JSON, statuses, bounded Retry-After, Unicode
  and redacted errors. Calls retain the fifteen-second deadline and no implicit
  retry; no transaction construction or signing moves into this adapter.
- Safe execution-status HTTP: 25 comparisons preserve validation, projection
  ordering, rate-limit responses and the eight-slot concurrency boundary. Native
  PostgreSQL verifies shared counters with Node and recovery after contention.
- Sandbox faucet adapter: 69 HTTP/validation/error comparisons and eight requester
  IP cases preserve the private loopback service, twenty-second deadline, quotas
  and request-ID disposition. Localhost Origin is accepted; ingress owns the
  backend client bearer. The legacy subprocess mode also passes 14 actual Node
  comparisons over synthetic executables, including dry-run output, buffer limits,
  quotas, ordinary errors and the existing production restriction. Standard asyncio
  subprocesses preserve argument/env handling and terminate at the deadline.
  Faucet errors now add a stable `code` and a `correlationId` shared with the
  backend failure log. Known quota, in-progress, uncertain, request-conflict and
  funding-failure outcomes stay distinct. The log records only the adapter stage,
  elapsed time, failure type and known upstream status/code; private response
  text, service credentials, URLs, wallet addresses and requester IPs are omitted.
  A deadline does not establish that no funds were added. Success responses,
  status mappings, Retry-After, request-ID disposition and funding behavior are
  unchanged. Focused HTTP regressions cover these outcomes and logging failure
  isolation within the existing local comparison suite.
- Recovery: 37 snapshot/page/cache comparisons, 16 actual Viem/Web3.py portfolios
  over local HTTP and 31 HTTP pagination/error comparisons. Standard ABI encoding
  and decoding retain uint256 values and EIP-1898 `blockHash`/`requireCanonical`.
  Canonicality is checked on cache hits; optional Fund failures preserve ownership.
  Retry-After reuses the qualified permissive Date adapter, as does RPC pacing;
  numeric delays and their existing bounds remain unchanged.
- Browser diagnostics: 46 actual Fastify comparisons preserve JSON parsing,
  explicit field projection, signed safe integer wallet/RPC codes, four-byte
  error selectors and redaction. Invalid optional error observations are ignored
  while the request retains its ordinary acknowledgement. Standard Python logging receives only
  the projected event; a failed logging handler cannot fail the product request.
  API/worker request logs now share request IDs with diagnostics; standard JSON
  logging is enabled in the process entry point. Prometheus request/cache/RPC and
  indexer gauges match retained metrics, keep unknown progress absent, exclude
  scrapes and preserve telemetry outage isolation. Product gauges also compare
  against actual retained Node across committed data, DB errors and changing assets.
  Scraping reads memory only. Worker engine integration remains pending.
- Alias signing kernel: 40 actual Viem comparisons covering Unicode messages,
  standard 65-byte and EIP-2098 64-byte signatures, recovery parity and
  retained rejection of EIP-155 recovery bytes. Standard compact normalization
  preserves the signed bytes and the shared consumed-nonce identity. Concurrent nonce consumption, durable writes and
  deletion preserve existing behavior; retained Node reads Python's writes.
  The alias HTTP controller passes 32 additional actual Node comparisons for
  UTF-16 lengths, validation, authorization-before-write and error behavior using
  injected authorizers. The runtime Date authorizer now compares 4,357 actual V8 timestamps in each
  of UTC/Paris/New York plus 40 authorization-order cases. Native configured
  HTTP verifies signed RFC timestamps, replay rejection, retained Node reads
  and deletion with consumed nonces preserved. The compatibility adapter retains
  [V8’s parser semantics](https://github.com/v8/v8/tree/main/src/date) and
  [BSD notice](NOTICE-V8.txt).
- Pydantic settings: 400 comparisons of existing formats, required values and
  value-free errors, plus 41 actual runtime profile comparisons. The local entry
  point wires gold/FX/RPC, activity and dashboard routes using these settings.
- Indexer identity, finality, raw log normalization and journal coverage: 314
  comparisons. Existing approved range subdivision/error/order behavior: 50 cases.
  These are worker foundations; the complete reconciler is still pending.
- Native PostgreSQL schema bootstrap preserves rows, shares initialization and
  reuses an eight-connection pool. Python and Node exclude each other through the
  same advisory lock. Journal reorg replacement, empty intervals and failed-write
  rollback are exercised. Snapshot persistence preserves the current model keys,
  four-snapshot retention and rewind deletion. Retained Node reads the resulting
  journal and snapshots; no schema migration or data restore is involved.
- Recovery-share persistence: 90 retained parsing/replay/checkpoint cases and
  native PostgreSQL bidirectional Node/Python writes preserve incremental/no-op
  checkpoints, profile/reorg rebuilds, wide balances and failed-replay atomicity.
- Holder/event projection and identity initialization: native PostgreSQL compares
  28 operations with the actual retained Node functions. Mint/transfer/burn and
  uint256 balances, clamped underflow/counts, delta rewind/rebuild/retention,
  incomplete-rewind results, current snapshot pruning and log deduplication match.
  Replaying a duplicate projected log does not apply its transfer twice. Timestamp
  rows compare in the retained Linux UTC profile, including extended years.
  Existing projection/raw identities and retained legacy Governance values are
  preserved; the complete collector/reconciler is now wired and compared below.
- Safe cursor/projection storage passes nine native Node/Python comparisons.
  Address-scoped ingestion passes ten native comparisons for retained counters,
  approved subdivision, raw-log identity, range replacement and replay coverage.
  The Safe collector passes 48 actual Node scan, committed-boundary, replay,
  malformed-log, cardinality and write-order comparisons. Five configured native
  PostgreSQL runs match Node for collection, replay, partial scans and continuation;
  unknown logs remain in the raw journal while only known executions are projected.
- Worker RPC uses standard Web3 JSON-RPC encoding/decoding and HTTPX transport.
  Twenty-four retained retry classifications and 32 actual Viem HTTP comparisons
  preserve ordinary three-retry behavior, raw-log single attempts, Retry-After,
  private headers, RPC-error precedence over HTTP status and cancellation. API RPC
  and lease transports retain their separate existing policies.
- Finalized Multicall preserves the existing budgets and exact canonical hash:
  11 batch plans, 12 multi-wave queue/error comparisons, six Viem/Web3 ABI byte
  comparisons and an actual aggregate wire/result comparison pass. Core/token
  metrics, basket reads and cached/pinned reference-price paths pass 29 actual
  Node comparisons with exact calldata and read targets. Recovery snapshot,
  dashboard construction and whole-worker integration are qualified below.
- Recovery-pool/Fund and indexed-asset reads: 38 retained snapshot/accounting,
  unavailable/terminal and schema-5 portfolio comparisons; six native indexed-asset
  SQL cases preserve snapshot/namespace limits. Exact ABI calldata matches Node.
- Dashboard construction: 43 bucket/window/supply/precision comparisons and eight
  native SQL cases preserve inclusive time bounds, ordering and the existing log
  limit. Completed JSON-number hydration matches Node after PostgreSQL expands
  numeric exponents; raw on-chain amounts remain decimal strings.
- Snapshot refresh: eight native Node/Python cases preserve legacy/V2 balances,
  model writes, canonical anchors/checkpoints and failed-finalize atomicity.
- Core/Governance collection: 102 strict/permissive event-decoding comparisons and
  18 native collector runs preserve unknown raw history, ordinary legacy modes,
  replay/reorgs, holder repair, partial completion and source-profile boundaries.
- Assembled worker: 24 configurations and ten cadence/lock/accounting cases match
  actual Node. Ops invokes its existing HTTP controls; starting the process adds
  no autonomous scheduler. Product refresh, fork readiness and shutdown use the
  same database/schema and the existing single-writer lock.
- Whole image: actual API and worker processes started through the installed Ops
  role commands pass synthetic chain-31338 and chain-1 replay. All durable rows,
  legacy/V2 models, Safe execution history and dashboard reads match retained Node.
  Retained Node resumes after Python writes without changing completed data.
  API metrics trigger no RPC work. SIGTERM during a real reconciliation completes
  its response/writes before worker exit 0; API shutdown also exits 0.
- Worker contracts: 215 actual Node comparisons for authorization, request/response
  envelopes, history progress and fork transitions; 54 worker HTTP comparisons
  preserve control responses and bounded diagnostics. Earlier control-domain fixtures use synthetic callbacks; the assembled image now exercises the actual engine.
- Direct-provider range signals: 60 retained error mappings and native Web3
  transport tests preserve approved HTTP 413/RPC -32005/-32016 subdivision,
  left-first coverage and terminal 429 behavior without implicit retry.
- Completed-reconciliation receipts: 868 actual Node stored-record and eight
  construction comparisons preserve version 2, wide decimal counts, finalized
  identities and detached RPC counters. Parsing a record alone does not establish
  coherent committed DB state. The durable reader now passes 109 actual Node
  comparisons for stored/working cursors, snapshot completeness and lease ambiguity.
  Twenty-six durable-count/receipt constructions and two atomic commit/deletion
  bindings also match. Native PostgreSQL verifies bidirectional Node/Python reads,
  atomic failed commits, partial-run receipt deletion and newer incomplete snapshots.
  The current direct-mode engine preserves Node's disabled broker-receipt policy; no completed receipt is invented for that mode.
- Private broker leases: 273 actual Node acquire/release/RPC comparisons, 53
  environment cases, 50 health cases and 16 retained runtime-policy cases preserve
  the expected revision/anchor, bounded contracts, expiry, frozen method accounting,
  exact range-reduction response and independent RPC errors. HTTPX and Web3's
  provider boundary share the acquired lease. The actual Linux image matches Node's
  four-request FIFO dispatch, busy release and header-slot behavior; cancelled
  callers free their queue slots and expired queued calls are not forwarded.
  The native fetch deadline is 35 seconds, with no implicit retry or direct fallback.
  The current engine uses retained ordinary RPC configuration. These historical lease domains are not activated by the language port.
- Sandbox fork recovery: 74 actual Node comparisons preserve preparation, prefix
  reuse, replay of advanced projections, divergent-history invalidation, readiness,
  idempotence and existing errors. Native PostgreSQL invalidation matches Node;
  failed writes roll back and Mainnet/aliases/nonces/quotas are preserved. The fork
  control boundary also matches 35 configuration, shared-lock, header and transaction
  paths. The complete engine supplies its RPC transport; these comparisons do not
  qualify a live refresh or installed generation; synthetic assembled fork readiness is qualified below.
- Standard Web3.py async transport preserves hash/`requireCanonical` values,
  uncached canonicality checks, private headers, deadlines and cancellation against
  a disposable loopback server. It is not wired to a deployed RPC endpoint.

Local comparison commands, from the backend repository with pinned Node 26.10:

```bash
uv sync --project python-candidate --frozen
bash python-candidate/tests/check-local.sh
docker build -f python-candidate/Dockerfile -t cybergold-python-candidate:market-parity python-candidate
python-candidate/.venv/bin/python python-candidate/tests/native_http.py
PYTHONPATH=python-candidate/src python-candidate/.venv/bin/python python-candidate/tests/native_whole_worker.py
FIXTURE_CHAIN_ID=1 PYTHONPATH=python-candidate/src python-candidate/.venv/bin/python python-candidate/tests/native_whole_worker.py
python-candidate/.venv/bin/python python-candidate/tests/native_worker_http.py
PYTHONPATH=python-candidate/src python-candidate/.venv/bin/python python-candidate/tests/native_safe_db.py
node --import tsx python-candidate/tests/node-gateway-lease-reference.ts > /tmp/cybergold-python-gateway-reference.json
python-candidate/.venv/bin/python python-candidate/tests/native_gateway_lease.py /tmp/cybergold-python-gateway-reference.json
```

The image fixture runs a synthetic in-container supplier, exercises the ten-second
market, fifteen-second RPC/Safe and twenty-second faucet deadlines, checks raw
responses/retry behavior, six Safe actions, canonical recovery portfolios and
correlated/redacted native JSON logs, memory-only metrics, a synthetic legacy
faucet executable and SIGTERM exit 0. The earlier worker control fixture exercises private authorization, a busy response and unknown progress. The assembled fixture exercises the actual worker through the installed role command, with a separate synthetic RPC container and configured API process. The database fixture creates fresh local
PostgreSQL and compares actual retained Node code with the candidate. Fixtures
use no deployed endpoint, database or real credential and are removed on completion.

The [local qualification record](qualification.json) binds the retained Node
source, candidate content, toolchain, local image and results. These comparisons
are migration evidence, not a new release gate.

H24 accepted the complete Python API/direct-mode worker in both installed
environments. The current local batch removes the old role-command translation
launcher and uses native Python commands. Ops selects those commands from the
canonical image runtime label; historical images retain their original commands.
Production listener/environment defaults remain. No Node runtime is shipped;
TypeScript domain code stays only as comparison/contract-generation tooling.
That migration originally preserved immutable images' rollback behavior; the
October 5 legacy recovery retirement below closes that projection's coexistence.
Do not combine this
language change with PostgreSQL relocation, shared-cache semantics, browser API
migration or protocol-monitor activation.

Upstream libraries: [FastAPI](https://fastapi.tiangolo.com/),
[HTTPX](https://www.python-httpx.org/),
[cachetools](https://cachetools.readthedocs.io/),
[Web3.py providers](https://web3py.readthedocs.io/en/stable/providers.html) and
[psycopg](https://www.psycopg.org/psycopg3/docs/) and
[Prometheus client](https://prometheus.github.io/client_python/).

### Browser fork-generation marker

`test_dashboard_generation.py` covers old/new/absent Sandbox anchors and the
unchanged Mainnet response. `native_dashboard_generation.py` exercises the
actual Linux API and disposable PostgreSQL, updates the existing anchor and
verifies that only the additive response field changes. Schema and snapshots
stay unchanged. [Qualification](fork-generation-qualification.json) is source
evidence; normal installed fork refresh and browser cleanup remain a separate observation.

## Helpers activity source — 2026-10-01

`HelpersCollector` uses the configured `NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS`,
existing finalized/address-scoped profile and the existing raw journal. Its own
cursor starts at `ONCHAIN_INDEXER_START_BLOCK` and advances by the existing
`ONCHAIN_INDEXER_MAX_BLOCKS_PER_RUN`; the Core cursor is never its backfill
boundary. A 500-block installed budget therefore requires multiple ordinary
runs to backfill the retained historical interval. Reorgs replace its changed
suffix, and the existing fork-generation transition invalidates or reuses its
rows. No schema, Core supply/reserve projection or frozen Core receipt changes.

`GET /api/activity/helpers` reads at most 100 journal entries in a repeatable
read-only transaction, with lossless amounts, nullable unknown historical
layouts and explicit start/cursor/hash coverage. It uses the existing backend
bearer ingress; no new frontend adapter or credential is required. Helpers
provider failures emit standard redacted JSON and retry on the next run without
blocking Core/Safe completion or fork readiness. Collection is inactive when
the existing address/profile is unconfigured.

All 16 canonical event decoders match actual Viem fixtures. The disposable
PostgreSQL fixture covers independent bounded backfill, caught-up no-op, small
budget reorg recovery, failure/cancellation, chain/address isolation, prefix
reuse and divergent fork invalidation, worker failure isolation and the bounded
HTTP view. It also passes inside the pinned `linux/amd64` image.
[Source qualification](helpers-activity-qualification.json) records the exact
image and limits; installed collection and historical migration decoding are
still separate observations.

```sh
PYTHONPATH=python-candidate/src python-candidate/.venv/bin/python python-candidate/tests/native_helpers_activity.py
```

Core and Helpers historical collection each use a 50,000-block pass budget,
on Mainnet and Fork. Stored profile settings remain unchanged; the worker
uses the larger collection budget. The owner selected half of
HEG's 40,000-request/hour allowance as an aggregate catch-up ceiling. Each of
the two configured environments gets 10,000 attempts/hour, evenly spaced at
0.36 seconds with no fresh burst on worker replacement. Both header and log
transports for Core, Helpers and its accompanying Safe collection share the
same pacer, including retries and adaptive subdivisions. They do not each
receive a separate 10,000-request allowance.
This counts client attempts; HEG retains enforcement of actual upstream usage.
Anvil cache hits may consume no HEG request, while upstream retries belong to
the broker/gateway's existing policy. Live App RPC reads use their existing
transport. No extra scheduler, schema or deployment gate is introduced.

Five pacing tests cover concurrent transports, retries, cancellation, live
transport isolation and process replacement. The actual HTTPX/Web3 and
PostgreSQL rehearsal advances both Core and Helpers by 50,000 blocks in one
pass on chain 1 and chain 31338, then completes the remaining history on a
second pass. Actual Core, Helpers and Safe requests share the allocation;
failure/reorg/fork recovery cases remain qualified. Successful worker
diagnostics report actual Core and Helpers RPC attempts and hourly allocation.

The fixture uses only its own disposable local PostgreSQL container. Its
`--dsn` / `--fixture` arguments support the same test in the local image. These
are local qualification commands, not a new CI or deployment gate.

## Basket preview source — 2026-10-01

The four fixed Helpers preview operations use standard Web3.py ABI encoding and
EIP-1898 canonical reads, with the same operation deadline and disconnect
cancellation as the existing focused pool API. All wide values and original
basket/ERC1155 ordering survive the JSON boundary. Invalid ABI inputs return
400; provider failures or a changed canonical block return a redacted 503.
[Qualification](basket-preview-qualification.json) records source comparisons
and the assembled image. Installed acceptance follows ordinary source delivery.

`tests/native_basket_preview.py` is an optional local rehearsal using only its
own containers and synthetic RPC. It is not a new CI or release gate.

### Helpers router facts

The fixed GET/HEAD `/api/governance/helpers-facts` operation uses the canonical
Helpers ABI for six concurrent reads at one EIP-1898 block hash. Decimal fee,
addresses, adapter list and boolean pause preserve ordinary partial failures,
missing optional configuration, canonicality, cancellation and the existing
serving deadline. `tests/test_helpers_router_facts.py` compares actual Viem ABI
bytes/results; `tests/native_helpers_router_facts.py` exercises the Linux image,
real HTTP/private transport, outage recovery, deadlines and disconnects.

## Token/native previews and Uniswap quotes — 2026-10-01

The configured Sandbox runtime (chain `31338`) enables the existing single
early probe for issue exact-in. Forced Core and automatic trade quotes share
the same Core engine. A supported selected typed route can become a usable
incumbent before exhaustive initial discovery finishes, after fresh exact-output
repricing, ordered shared-pool composition, the full protected Helpers preview,
capacity checks and canonicality. Estimates alone remain indicative. Full search
continues and may refine that incumbent; its existing deadline, route coverage,
input budget and execution tolerance are unchanged. An ordinary search-tail
failure can retain that checked tuple; reorgs and caller cancellation retire it.

The early probe adds RPC and SDK work and can consume its one attempt on an
unsupported or unfillable first route. It does not guarantee the exhaustive best
route or fix every quote timeout. Mainnet keeps the issue probe disabled. Redemption exact-out can refine one
fresh protected Helpers point outside the existing output interval using the
ordinary integer gross correction. It freshly reprices the resized selected
routes, composes shared pools in Core order and checks the full Helpers output
and canonicality before retaining a quote. Full route coverage continues and can
improve that quote; existing output bounds, deadlines and cancellation remain
unchanged. The first usable quote can require more Core than the complete-search
optimum, and the refinement can add RPC and SDK work. Sandbox transaction and
frontend amount acceptance are recorded separately in the Ops regression workplan.

The subsequent [unified trade coordinator](../docs/unified-trading.md) owns
Core basket seed construction and compares complete qualified Core/market
candidates for one App intent. It retains the family APIs described below;
their historical App-owned request construction is no longer needed by the
unified trading surface. Source qualification covers all four Core modes,
independent provider failure, explicit plan revalidation, one-head sharing,
model warm reuse, canonical invalidation and last-subscriber cancellation.

The quote-intent stream accepts optional integer `slippageBps` (default `100`,
equivalent to 1%). It adjusts execution amount limits; raw expected inputs are
reported separately in `expectedInputAmount` for exact-output requests. Token
and native input-budget issuance still execute the deployed fixed-output route.
For those quotes, `requestedGrossCygldOut` / `requestedNetCygldOut` describe the
unclipped quoted basket (gross uses the canonical mint for the recipient net),
while `remainingGrossCapacity` / `remainingNetCapacity`
use Core and Helpers getters at the quote's canonical block. They let the UI
reject an oversized requested issuance without silently adopting the clipped
purchase. Selected plans carry their original `slippageBps`; a different
tolerance rebuilds execution limits through the ordinary quote path.

The six token/native Helpers previews and configured QuoterV2 exact-input/output
reads are fixed typed operations. Web3.py preserves existing ABI bytes, opaque
route legs, asset ordering and wide decimal-string amounts at one canonical
configured-chain block. Caller-supplied targets/providers are not used. The App
keeps route selection, tie handling, slippage and wallet intent. No schema,
signing or required CI job is added.

[Local qualification](token-quotes-qualification.json) records ten actual Viem
wire comparisons across eight modes against the assembled Linux API. Focused
source comparisons and the existing canonical backend suite pass; provider
outage/reorg, invalid ABI inputs, disconnect cancellation, existing serving
deadlines and shutdown are exercised with disposable synthetic fixtures. No
installed RPC endpoint or database is used. Run the optional native rehearsal
with `python-candidate/.venv/bin/python python-candidate/tests/native_token_quotes.py`
after building the local image named in that test. Installed API/browser
acceptance remains separate in Ops' U5 release record.

## Fresh permit preparation facts — 2026-10-02

`GET /api/account/core-permit?owner=...` reads the configured Core name and
owner nonce. `POST /api/account/permit2` selects only the App's three fixed
operations: configured Helpers router/bytecode verification, the owner's first
unused bitmap nonce, or ordered ERC20 allowances for its selected tokens. All
reads use one canonical configured-chain block, standard Web3.py ABI encoding
and the existing disconnect/deadline transport. Nonces and allowances remain
lossless decimal strings. Full bitmap words advance until a free bit is found
within that existing operation deadline; there is no new word-count restriction.

These observations are fresh and never reserve a nonce or choose an approval.
The App retains its configured signing domain/spender, value/deadline, live
wallet chain check, signing, approvals and submission. Failure is unavailable,
never a zero nonce or a previous allowance; migrated reads do not fall back to
browser RPC. Caller-supplied ABIs, providers and contract methods are absent.

[Local qualification](permit-context-qualification.json) records sixteen focused
backend tests and ten actual Viem wire reads through the assembled Linux API,
including a full bitmap word, wide amounts, concurrent owners, reorg/outage
recovery, malformed inputs, cancellation and the inherited deadline. No
deployed endpoint, database or wallet signature is used. The optional native
rehearsal is `python-candidate/.venv/bin/python python-candidate/tests/native_permit_context.py`
after building the local image named in that test. It adds no release gate.


### Selected ERC20 metadata, native permit context and exact approval

`GET /api/tokens/metadata?token=ADDRESS&holder=ADDRESS` resolves a selected
ERC20 through concrete configured-provider operations. The optional holder adds
only that token's balance. `purpose=balance` reads only its balance/context for
wallet refresh and preflight; metadata fields and authorization explicitly report
`not-requested`. This path performs no domain or disposable-signature discovery,
including after reusable metadata expires. Name and symbol accept standard strings or legacy
bytes32; decimals and balance failures remain explicit rather than supplying a
fabricated precision or zero. Identity is the configured chain plus checksum
contract address; native ETH keeps its existing separate API.

`GET /api/account/token-permit?token=ADDRESS&owner=ADDRESS` reads the owner's
nonce and allowance to the configured Helpers fresh at the same canonical
block. The App chooses the purchase ceiling/deadline and signs. Reusable token
metadata and optional capability observations share the existing process-local
`SharedReads` cancellation behavior and a lazy 30-day maximum completion
lifetime, including observed negative or unconfirmed permit support. The next
selected-token request after expiry repeats discovery, allowing a token that
adds permit support to qualify later. Every metadata or permit-context request
still reads the domain separator fresh; a changed or newly available separator
discards the previous entry immediately. RPC unavailability is never cached.
This is bounded process memory (512 entries), cleared on process close, with no
cron task or operator command.
User nonce, allowance and balance are never cached. These token operations do
not require an unrelated Core or governance configuration binding.

Authorization distinguishes `erc2612`, `variant` (initially recognized DAI),
`none`, `unknown` and `unavailable`. Domain introspection preserves ERC5267
fields, including salt and omitted version; unfamiliar extensions keep unknown
support. Legacy fallback tests only bounded common domain candidates whose
hash matches the observed separator. PAXG/XAUt version 1 and USDC version 2
supply established domain descriptions, without creating an execution allowlist.
An introspected domain chain ID above JavaScript's safe integer range is a
lossless decimal string; current configured chain IDs retain their number form.

Optional functional qualification uses a fresh unfunded account generated in
process memory. One read-only Multicall3 `eth_call` runs an invalid permit,
reads unchanged nonce/allowance, applies a valid permit, then reads incremented
nonce and exact allowance in that same discarded state. Empty return data or
readable getters alone never qualify standard permit semantics. No key,
signature or signed calldata reaches API responses, persistence or logs. A
qualification failure changes only optional native authorization; token quoting
and ordinary approval retain their existing independent contract errors.

`POST /api/transaction/token-approval-gas` accepts `{ owner, token, amount }`
and estimates the exact ERC20 `approve(configured Helpers, amount)`, including
amount zero for an ordinary zero-first reset. The spender stays configured;
nonstandard approval return values are not decoded. Helpers execution now
also accepts `issueFromTokenExactOutWithPermit` and the existing
`issueFromTokenExactOut` allowance operation. Both preserve the exact caller
arguments, latest-state simulation and estimation; quote economics are unchanged.
`GET /api/governance/helpers-facts?tokenPermitIssuance=true` opts into the
existing Diamond `facetAddress` observation for selector `0x462835d6`. An absent
selector is false, and a read failure remains unavailable. Ordinary Helpers
facts retain their previous read workload when the option is absent.

The same selected-token permit context serves basket inputs and CYGLD
redemption: it reuses the existing monthly capability entry while rereading the
owner's nonce and Helpers allowance. The Permit2 context's existing
`allowances` mode reads the distinct token-to-Permit2 setup allowances in one
request with deduplicated tokens and bounded dispatch. No new context endpoint,
wallet cache or spender-selection parameter is needed.

Helpers execution also accepts `issueFromBasketExactInWithMixedPermits` and
`issueFromBasketExactOutWithMixedPermits`, preserving the ordered basket input
vector and compact Permit2 subset supplied by the App. Existing ordinary
`redeemToBasketExactIn`, `redeemToTokenExactIn` and `redeemToNativeExactIn`
operations allow the App to reuse sufficient legacy Helpers allowance without
another signature. Authorization amounts and user intent remain caller-owned;
simulation still precedes gas estimation.
`basketPermitIssuance=true` on the existing Helpers facts endpoint opts into
separate `basketPermitIssuanceExactIn` and `basketPermitIssuanceExactOut`
selector observations. Each reports installed, absent or unavailable
independently, allowing the App to keep the installed legacy Permit2 route on
older targets. Bare Helpers facts do no additional selector reads.

The local comparison suite includes the focused token/permit tests. Actual-token
read-only qualification can be repeated with the existing authenticated adapter:

```sh
PYTHONPATH=python-candidate/src python-candidate/.venv/bin/python \
  ../cybergold-ops/scripts/authenticated_rpc.py --target mainnet -- \
  python-candidate/.venv/bin/python python-candidate/tests/native_token_permit.py \
  '{RPC_URL}' 1 /tmp/token-permit-mainnet.json
```

Use `--target fork-full`, chain `31338`, and another output path for Sandbox.
This checks token behavior and discarded permit state semantics; it does not
install a Helpers facet or claim an integrated purchase/wallet qualification.

## Recovery assets and fee context — 2026-10-02

`GET /api/protocol/recovery-assets` reads only the configured Core's attached
recovery assets, in contract order. Empty success remains distinct from failure;
the App retains redemption minima and share identifier construction.
`GET /api/transaction/fees` preserves the existing Ethereum App's EIP-1559 fee
estimate: integer 1.2 base-fee multiplication and priority-method fallback to
`max(0, gasPrice - baseFee)`. Direct standard provider transport avoids Web3.py's
additional fee-history fallback. Wide fee values remain decimal strings.

Both operations use fresh configured-chain/canonical block context, the existing
serving deadline and caller cancellation. Unsupported fees and provider failures
remain unavailable. No database, cache, caller ABI, signing or submission is added.
[Qualification](recovery-fee-facts-qualification.json) records thirteen focused
backend tests, nine actual Viem fee comparisons and the assembled Linux API's
ordered/empty assets, supplier failures/recovery, reorg, deadlines, cancellation
and native shutdown. `tests/native_recovery_fee_facts.py` is an optional disposable
local rehearsal using its named image; it adds no required CI job or release gate.

## Focused transaction preparation — 2026-10-02

The Apps now have five additional fixed operations:

- `GET /api/governance/authority` observes configured diamond pause/Safe wallet
  and existing `canPause`/`canUnpause` facts. Missing configuration/account and
  individual failures remain explicit; the App decides action eligibility.
- `POST /api/transaction/recovery-redemption` simulates the configured Core's
  exact `redeemRecoveryShares`, preserving holder/recipient, shares and minimum.
- `POST /api/transaction/permit2-approval-gas` estimates the existing ERC20
  `approve(configured Permit2, maxUint256)` operation. The App retains its gas
  padding and existing failure fallback.
- `POST /api/governance/safe-execution` simulates the exact Safe execution,
  including executor nonce and signatures. False remains false; native reverts
  remain unavailable. Existing App signature/nonce checks and submitted bytes stay
  in the wallet flow.
- `POST /api/transaction/helpers-execution` serves the seven signed Swap fee
  hints, using the shipped Helpers ABI and configured target. Nested integer
  arguments use decimal JSON; simulation precedes native latest-state estimation.
  It accepts no ABI, provider or contract target from the frontend.

Latest-state simulations/estimates are observations, not execution reservations.
No shared account cache, signatures, broadcasts or receipt tracking are added.
The inherited operation deadline, cancellation and private-error redaction remain.
[Qualification](transaction-preparation-qualification.json) records 31 focused
backend cases, three Safe payloads and fourteen actual Viem Helpers wire cases,
followed by complete source comparisons and the assembled Linux API rehearsal.
`tests/native_transaction_preparation.py` uses its named local image and synthetic
RPC only; it adds no required CI job or deployment gate. Publication and installed
acceptance remain separate from this local record.

### Standard receipt confirmation and replacement observations

Four fresh GET operations under `/api/transaction/wait/` supply `head`,
`transaction?hash=…`, `receipt?hash=…` and `block?blockNumber=…`. The block read
includes native transactions for sender/nonce replacement matching. Head and
block request numbers use decimal strings; returned transaction/receipt/block
fields preserve Ethereum's standard wire representation for the pinned Viem
formatters. Absence stays null and provider failures remain redacted errors.
The App reuses Viem's existing waiter, confirmations, retries, timeout and
repriced/cancelled/replaced callbacks. This service performs no tracking,
interpretation, signing or broadcast and accepts no arbitrary RPC operation.

[Local receipt qualification](receipt-wait-qualification.json) records seven
focused backend cases and fifteen actual Viem/Wagmi transport cases, all four
Linux HTTP routes, deadline/disconnect behavior and complete source/browser checks.
Five direct App wait consumers and both standard Wagmi receipt hooks use these
operations. The transport also serves RainbowKit's existing receipt waiter.
Its other wallet-library reads and Wagmi's standard revert replay retain the
compatibility transport. Original per-call request options, zero HTTP retries
and the twenty-second frontend request timeout are preserved.

### Permanent recovery precision and destination code observations

`GET /api/protocol/recovery-share-precision?asset=…` reads the configured Core's
permanent `recoveryPool.shareDecimals`; basket membership and ERC20 decimals do
not define recovery precision. The App uses that precision for quote shares,
including zero decimals, or labels the quantity raw when unavailable.

The existing Helpers facts GET optionally accepts the App's `adapter` address
and returns its code presence at the same canonical block as approval-list
membership. Bare Helpers observations remain unchanged. The Swap consumer uses
this fresh pair for its existing pre-signing check. Empty code is distinct from
a failed supplier; no new approval policy or configured-service requirement is added.

`GET /api/governance/target-code?address=…` supplies code presence for the App's
Safe proposal destination description. It reuses the principal code transport
without extra Safe owner/threshold reads. The original contract-call, EOA and
Safe rejection interpretation stays in the App; supplier failure supplies no
EOA classification. Neither operation interprets authority or submits transactions.

[Local qualification](remaining-reads-qualification.json) records six precision,
ten Helpers/adapter and six proposal-target backend cases, focused App tests,
three rendered precision cases, complete source/browser checks and the same
disposable native API rehearsal. Existing fifteen-second operation deadlines,
cancellation, canonical reads and redaction remain. No installed acceptance or
new required CI/deployment gate is implied by this local evidence.


### Wallet-library native balance and ENS records (local source batch)

`/api/account/native-balance?holder` observes only the holder's native ETH,
without reading unrelated tokens. Standard Wagmi balance formatting and zero/
wide integer values are preserved. Historical/pending library reads remain
compatible. Six native-source cases and five actual Wagmi/transport cases pass.
`purpose=display` opts ordinary native balance loading into reading only the
latest block and the EIP-1898 hash-pinned native balance, without the repeated
chain check or final
block reread (two RPC requests instead of four). Full wallet display uses the
same explicit display marker and initial block, with all seven balances inside
one canonical Multicall3 aggregate read.
Both endpoints retain their existing chain and final canonicality checks for
unmarked, `purpose=swap-preflight` and other requests. Older Apps and already-open
tabs keep their original behavior; older backends ignore the extra parameter,
so either update order is compatible.

`/api/account/ens-name?holder` and `/api/account/ens-avatar-record?name` use
[Web3.py's native AsyncENS](https://web3py.readthedocs.io/en/v8.0.0/ens.html),
pinning calls to the same canonical configured-chain block. Primary names retain
forward-address verification; no record is null, provider failures are unavailable.
Six native ENS cases cover encoding/decoding, mismatched forward addresses, URI
preservation, HTTP validation, redaction and cancellation. The App uses Wagmi's
supported custom client factory and six actual name/avatar query cases; Viem
continues to parse HTTP/IPFS/NFT avatars. The native backend now reads standard
ERC721 `tokenURI` / ERC1155 `uri` at the same canonical ENS block and supplies
that optional result to the maintained Viem parser. It does not fetch images or
metadata. Unsupported/historical requests return their ordinary failure without
a generic browser RPC fallback in the current App client. No caller-selected
resolver/ABI/provider is added.

Web3.py 8 calls its Unicode normalizer with character lists; pyunormalize 18
rejects those inputs. The hashed lock pins compatible 17.0.0. ENS's default
wall-clock stale-chain middleware is removed: the existing canonical configured
chain contract remains, and an intentional Sandbox fork's source timestamp is
not a new availability gate.

The App's ISO millisecond timestamps now use Python's native parser first,
without rewriting the bytes covered by alias signatures. Four focused cases
cover pre-epoch values, shared compact/standard replay identity and altered/
expired payload rejection. Historical timestamp formats retain the qualified
adapter until their support can be removed explicitly.

The inherited fifteen-second bound covers each complete serving operation;
it does not limit a wallet's multi-poll receipt confirmation wait. The App's
HTTP timeout is twenty seconds. Native assembled deadline/cancellation tests
cover bounded failure and recovery; no observed operation justifies extending
this bound. Alembic is additive explicit tooling under [schema/README.md](schema/README.md),
with no automatic schema change during API/worker startup or physical relocation.

RPC failure context is optional in the existing JSON and quote-stream error
envelopes, route failures and correlated request logs. `diagnostics` reports
available method, stage, elapsed milliseconds, upstream code/HTTP status and
sanitized provider text. `failureType` distinguishes `rpc-error`, `http-error`,
`provider-timeout`, `backend-deadline` and `transport-error`; unknown facts stay
absent. Provider URLs, RPC parameters and authorization values are never echoed.
The existing deadlines, retries, cancellation and frontend messages remain
unchanged.

When every route candidate fails, quote aggregation retains the selected
candidate's existing RPC diagnostics in the terminal stream error and its
correlated log. Error code and details stay tied to the same candidate. This
also covers exact-out seed construction, retained-plan revalidation and retained
capacity reads. Empty or zero-quote results retain their previous classification
without invented diagnostics; contract-only exact-out failures retain their
previous category. Regression cases exercise all four quote modes and redaction
through the public stream and log.


`/api/transaction/revert?hash` serves the standard Wagmi receipt-hook replay.
Web3.py reads the original transaction and replays its fields at latest state;
five native cases compare all five Ethereum transaction-type call shapes with
actual Viem. Native return bytes and ContractLogicError data remain distinct
from missing transactions, transport errors and provider messages. The App's
supported action override keeps standard waits/replacements and uses Viem's
standard Error/Panic ABI decoding. Five actual Wagmi cases cover reverted
replacement identity/callbacks, failures, success without replay and decoded
errors. This reports latest-state replay evidence, not proof of the historical
revert, and accepts no caller calldata or signing/submission operation.

## Native process and ENS NFT local batch — 2026-10-02

The root and candidate Dockerfiles now have a native API default command and
`io.cybergold.backend.runtime=python`; the worker uses its own Python module.
The obsolete translation launcher and Node production entry/build modules are
removed. Node libraries are development-only comparison/contract-generation
tooling. Existing immutable images retain their original Ops launch commands.

[Qualification](native-process-qualification.json) records actual default-CMD API
startup, native worker reconciliation/shutdown and retained Node database replay.
Eight ENS cases include standard NFT token URI methods, wide token IDs, canonical
block context and per-record failure. This source batch is local; installed
selection follows the final grouped release.

## Backend audit corrections October 3 2026

Holder balance/count/delta writes now share a transaction during transfer,
rewind and rebuild. A projected transfer and its event deduplication key commit
together. Signed alias mutations commit their nonce with the edit, allowing
the same signed request to retry after a database failure while preserving
replay rejection after success. Safe event failures use a sanitized correlation
ID response; existing validation and rate-limit errors retain their messages.

The complete worker operation retains the existing advisory lock after caller
cancellation, through completion writes and Helpers collection. Shutdown drains
these surviving operations before closing the database. Allowance reads
deduplicate tokens at the pinned block and expand results back into the original
order. Allowance and authoritative-pool operations dispatch at most eight
suppliers concurrently per operation and cancel sibling work on failure or
deadline. Every distinct input still runs; there is no new request quota or body
ceiling. The existing fifteen-second operation deadline remains in effect.

The local comparison wrapper includes the audit's resource, redaction and
cancellation regressions. The optional native fixture tests ordinary SQL
failures, retry, concurrent nonce reuse and the retained healthy holder/Core
comparison matrices against its own disposable PostgreSQL container:

```sh
bash python-candidate/tests/check-local.sh
PYTHONPATH=python-candidate/src python-candidate/.venv/bin/python python-candidate/tests/native_audit_remediations.py
```

Run from the repository root with its frozen Python environment, npm development
dependencies and pinned Node version. The native command additionally requires
local Docker and uses only generated test accounts and public fixture credentials.
Retained Node source stays the historical comparison reference; failure-path
corrections intentionally differ from its old behavior. No new CI job or schema
change accompanies these corrections.

## Legacy recovery projection retirement October 5 2026

The owner selected BQ4 alternative 3 and authorized proceeding with retirement.
Completed snapshots now commit the configured V2 projection, its checkpoint,
recovery/dashboard models and finalized snapshot keys in one transaction, without
replaying lifetime ERC-1155 history into `onchain_recovery_share_balances`.
Recovery HTTP reads continue using the existing RPC portfolio reader. Ordinary
non-V2 configuration still publishes its models; retirement adds no required
setting, admission rule or schema-version change.

This release closes support for rollback consumers that require maintained
legacy recovery rows, including the historical Node SQL portfolio reader.
Retained TypeScript remains a historical test oracle. An earlier immutable image
has its original behavior, but legacy-row coexistence is no longer a supported
contract for data produced after retirement. Choose a rollback image with the
RPC reader and retired writer; do not restore a stale database to roll back code.

Existing legacy rows are left untouched by snapshot refresh. Ops owns their
one-time removal after adopting this source. The empty table remains in schema
12 for existing seed manifests and reset tooling; retirement does not drop the
table, rewrite archives or delete journal/V2/model data. Existing holder/fork
reset paths can still clear this inert table. V2's separate 100,000-log replay
window and 100,000-balance limits remain, including full backfill/reset limits.

The native regression fixture reproduces the old failure with 100,002 retained
transfers, verifies successful incremental completion with a uint256 balance,
checks non-V2 publication, and injects a dashboard write failure after V2 and
recovery-model writes to verify rollback and retry. It also verifies the existing
V2 replay limits and eight historical anchor/model comparisons:

```sh
PYTHONPATH=python-candidate/src python-candidate/.venv/bin/python python-candidate/tests/native_legacy_retirement.py -v
```

Use the frozen Python environment, pinned Node/npm dependencies and local Docker.
The fixture uses a cached `postgres:18-alpine` image and removes its disposable
container. Historical qualification JSON files continue to describe their
original source; they do not attest to this retirement release. No hosted CI
change accompanies BQ4; the separately accepted BQ5 workflow work remains future.

## Head-aware quote reads — 2026-10-04

The lightweight receipt-wait head now also returns `blockHash` and decimal
`blockTimestamp`. The browser uses the hash to refresh quotes and fee pricing;
slot time is only a scheduling hint. Receipt confirmation and finalized indexing
still use observed chain data, never a clock's prediction of finality.

Identical overlapping hash-pinned `eth_call` reads share their producer. Route
searches share overlapping factory/liquidity batch members and retain successful
pool observations on chain 1, keyed by exact hash, target and calldata. Their
bounded process-local cache never retains failures or amount-dependent Quoter
results. Sandbox only shares in-flight reads: privileged fork overrides can
change state without changing its header hash, so sequential pool reads remain
fresh. Canonicality and chain checks remain fresh on those quote operations. Cancelling
one subscriber leaves another active subscriber running; the last cancellation
releases unused work. No execution admission rule or lifecycle marker is added.

Route metrics distinguish issued `rpcReads`, logical `rpcReadsRequested`,
`rpcReadsCoalesced` and completed `rpcReadsReused`. Five simultaneous fresh
fixture searches preserve all candidates while reducing issued reads from
135 to 71 (47.4%) on the WETH path and 315 to 179 (43.2%) on the generic path.
Warm chain-1 pool observations reduce a later fresh-amount WETH search from
27 to 11 reads (59.3%). These measure RPC counts, not deployed response latency.

Gold and FX response freshness is the remaining acquisition lifetime: a nearly
expired Valkey payload cannot acquire a full new HTTP lifetime. Stale/expired
responses are no-store. Run `bash python-candidate/tests/check-local.sh` with
pinned Node and the frozen Python environment for the existing comparison suite
and sharing, same-height replacement, fork override and market-age regressions.

The API's existing Sandbox generation observation also retires optional quote
models from the previous fork. It reads the worker's durable marker before the
dashboard snapshot, so rebuilding projections cannot preserve an old capacity
hint. The first known generation and each subsequent change clear organic
history and cancel optional acquisitions; in-flight operations cannot republish
retired model frames. Exact quote results, RPC reads, deadlines and errors remain
unchanged. Mainnet and repeated observations of the same generation retain their
models. The comparison suite covers delayed acquisitions, in-flight facts and
quotes, shared model replay, and unavailable snapshots during fork catch-up.
