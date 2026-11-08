# Quote processing specifications

This document describes the implemented quotation mechanism. It is not an
improvement proposal or a performance promise. Changes require the owner's
explicit authorization under [AGENTS.md](AGENTS.md), together with the
corresponding implementation and diagram updates.

The initial review describes Backend Dev `8b8a64ac7ce2f0faa46d42653615d2f8aee1c930`.
The initial App consumer review describes App Dev
`1b0bc8d761f6d891547c3c224792bdc3e01d2d7c`. These references identify the
reviewed implementation; they are not runtime admission conditions.

## Read the mechanism visually

These editable diagrams are dependencies of this specification. Their arrows
describe dependencies and concurrent work, not a timeline drawn to scale.

1. [From an input change to a displayed quote](docs/specs/diagrams/01-app-to-quote.svg).
2. [Inside Backend: retained routes, initial paths and continued search](docs/specs/diagrams/02-backend-fast-and-search.svg).
3. [Market-only and market + Core paths](docs/specs/diagrams/03-market-and-core.svg).

The same three pages are available as an
[A4 landscape process document](output/pdf/quoter-current-process.pdf).
Measurements, latency objectives and improvement proposals are maintained
separately in the Ops workplans area.

## The three things that can appear

| Item | Meaning | How it is obtained |
| --- | --- | --- |
| Route proposal | Pools, directions, splits and Core composition that might work | Retained route history, CyberGold discovery or Uniswap tools |
| Arithmetic estimate | Indicative output calculated from cached economic samples or a model | The estimate/model path; it is not a new complete Helpers simulation |
| Validated quote | A complete economic observation produced by Helpers execution simulation | A previously validated stored observation, or a newly measured observation |

Both stored and newly measured validated quotes can be selected for display.
A stored observation does not acquire a new observation time merely by being
displayed. `observation.source` distinguishes `stored` from `search`; this is
provenance, not an additional requirement for displaying a selected quote.

The requested budget and the quote's funded input are different fields.
An existing validated route can fit under a larger budget while spending less
than that budget. An arithmetic full-budget estimate remains an estimate.
Cached input-limit evidence and budget reconstruction are separate from simply
having a partially funded observation.

## Entry points and ownership

| Entry point | Responsibility |
| --- | --- |
| `POST /api/economic-quotes/stream` | Stream Backend-selected whole quotes and subsequent updates as NDJSON |
| `POST /api/economic-estimates` | Return an advisory cached-model packet as JSON |
| `POST /api/tx-preparations` | Re-simulate a captured selected plan and construct execution terms after selection |
| `GET /api/protocol/config` | Supply configured contract and token identities used to construct requests |

The Backend owns route history, family selection, candidate ranking, route-tool
adapters, economic evaluation and quote publication. The App owns input,
request lifetime, formatting and display. The App has no shared executable
quote-history cache or independent economic winner selection. Its model-query
reuse is advisory and distinct from Backend whole-quote history.

## Step 1: make an App request

For the reviewed exact-input token flow, the App parses a positive amount using
the available token metadata and configured Core/Helpers addresses. Typing uses
the existing 100 ms debounce. Explicit Refresh uses the current amount without
another typing delay. Basket input handling has separate dependencies below.

The advisory model request and the quote stream run independently. A late model
response does not hold or retract a selected current-search quote, or a
full-funded/known-limited stored quote. Head watches,
balances, wallet connection and transaction preparation are not prerequisites
for this token quote stream. A cold page can still need assets, hydration,
configuration and token metadata before it can construct its first request.

The Next proxy forwards the stream without collecting the complete search
result. Its JSON endpoints collect the upstream JSON body before returning it;
this difference does not turn the quote stream into a buffered JSON request.

Backend emits `X-Accel-Buffering: no` for its NDJSON responses. The App sets
that header independently on its fixed streaming proxy responses, even when
it is absent from the upstream headers. Each response asks its receiving proxy
to avoid buffering; this is not a public-delivery measurement. Nginx can
[apply the response header](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_buffering)
and [omit it when forwarding](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_hide_header),
and proxy configuration can disable processing of that control. Header
presence or absence at a later hop does not establish when bytes were flushed.

## Step 2: consult validated history and start work together

For scalar intents (`0`: token to CYGLD; `1`: CYGLD to token), the Backend:

1. Captures the operation's available local cache scope.
2. Offers fitting exact and neighboring in-memory observations to its quote book.
3. Publishes the book's available stored winner and yields to delivery before
   copying route seeds or scheduling new search work.
4. Starts retained-route replay, ordinary search and the publication consumer.
5. Recovers metadata/SQL scope and optional persisted history concurrently.

The in-memory history path does not await SQL recovery, SDK pricing or a new
chain read. Publishing an already validated history observation adds no new
Helpers RPC. Optional history failure does not cancel ordinary exploration.
Cache persistence is asynchronous relative to publishing a selected frame.

History and route seeds are maintained for both `market` and Core-containing
families. Lower and upper neighbors in each family can seed new amounts: up to
four distinct neighboring candidates when available. Equivalent bodies are
deduplicated. Reconstruction can reuse the backward-input calculation when
an otherwise promising route cannot consume the proposed funding.

Non-scalar Basket intents have a separate cache-first entry path; the scalar
in-memory independence above is not a claim that every Basket lookup follows
the same sequence.

## Step 3: obtain a complete path

There are concurrent ways to obtain a complete proposal:

- **Retained path:** reuse a known whole-plan topology and evaluate it with the
  appropriate funding. It does not need rediscovery or SDK pool snapshots.
- **Initial constructed path:** the initial `first=True` grid nominates AMM
  topology, constructs a whole plan and proceeds to Helpers. When custom
  discovery is enabled, direct pools and a single connector beside the current
  seed are tried before the full custom graph walk. The adapter retains its
  native/anchor rules, encoding checks and ordinary later discovery. This first
  pass deliberately bypasses SDK amount-pricing. Repeated initial consumers of
  the same segment can reuse that short prefix while its registered query has
  no ready supplier or completed-topology offer. Query registration alone does
  not force a later initial whole-plan consumer through the full graph. Actual
  ready offers retain their existing precedence.
- **Continued exploration:** detailed SDK simulation, alternative allocations,
  router hints, residual handling and repairs propose further complete plans.

After a Core-issuance whole plan receives a generic Helpers contract rejection,
search can nominate one distinct body that retains actual basket residuals
instead of routing them to CYGLD. Its acquisitions, allocations and funded
inputs are unchanged. Empty asset-to-Core continuation templates return the
complete residual input through the existing adapter; Helpers measures it as a
retained charge, without adding residual AMM output. This alternative requires
another whole Helpers observation before selection. Contract-rejected bodies
keep their ordinary error/invalidation handling and residual-route exploration.
Transport failures and typed protocol errors do not trigger this alternative.
Selected-plan preparation replays the accepted body without substituting it.

Core construction fields are prepared independently. A pure-market proposal
does not need the Core basket basis. A newly constructed Core-containing
proposal needs its real basket assets/weights or output identities to encode
that operation. An already encoded retained Core body goes directly to Helpers
without awaiting those construction fields again. Core
state is warmed independently, cached and invalidated through the implemented
generation/event mechanisms; missing fields are coalesced and independent
reads can run concurrently.

Ordinary custom discovery walks and sorts its reachable single-path graph;
the initial short-path prefix above does not await that walk. Both have
cooperative checkpoints, while split enumeration remains lazy. Initial prefix
duplicates are reconciled with the normal nominations by the same route identity.

## Step 4: use route suppliers for the market legs

The same AMM adapter serves pure market paths, Core basket acquisitions,
residual conversions and redemption market outputs. A supplier query identifies
a source, destination and amount. The bootstrap starts the pending suppliers
without waiting for one supplier to finish before starting another:

- CyberGold custom discovery;
- AlphaRouter;
- UniRoute local;
- UniRoute API;
- GuideStar API.

These are demand-started per market segment, not all queried globally at HTTP
ingress. AlphaRouter and UniRoute local can emit topology hints before deeper
optimization finishes. Their engine-owned child processes are reused but are
started lazily. The generic SDK arithmetic child is also reused and lazy.
Initial custom-prefix nominations contribute to their supplier's candidate
count and first-candidate time; lazy-feed reads remain a separate measurement.

Hosted adapters use Uniswap Trading API endpoints. Their labels do not prove
which undocumented server algorithm ran. Recorded response evidence determines
attribution. On Sandbox, hosted discovery supplies the foreign market topology
and the local adapter stitches the fork-only Core/PAXG anchor where required.

The two hosted adapters share their own FIFO start-pacing queue, separate from
the RPC broker. The implemented default is six starts per second; HTTP
responses may overlap. HTTP status, queue wait and physical attempt accounting
are recorded. A 429 cooldown affects later starts. A no-route result belongs
to that supplier and is distinct from an RPC transport failure.

## Step 5: measure the complete proposal in Helpers

Once the whole path is built, the canonical evaluator performs:

```text
encode body and simulation funding
  -> acquire existing engine work permission (or share an identical call)
  -> eth_call Helpers.executeExactInput at latest, with funding state overrides
  -> decode execution result, account for fees/retention, produce whole quote
```

This is a simulation, not a transaction submission. Both pure-market and
market + Core plans use this complete execution boundary. One such call
measures all encoded market/Core actions in their actual order, including
shared-pool effects. It is not one external RPC per market leg.

Simulation funding changes only the synthetic payer's native balance,
input-token balances and Helpers allowances. Core total supply, reserves,
pool state and contract code retain their ordinary chain state. A qualified
quote is therefore a whole-plan execution observation under simulation funding;
it does not prove the real wallet can fund or authorize that plan. A stored
observation proves its recorded simulation, not execution at the current head.
Only encoded actions are exercised: a pure-market CYGLD sale does not establish
Core-redemption coverage.

Protocol shortages remain distinct from wallet funding failures. Core checks
`InsufficientCygldSupply` against the gross CYGLD burn. Its exact-input
redemption calculates current outputs, rejects unmet minima with
`RedemptionOutputBelowMinimum`, and rejects an all-zero settlement with
`RedemptionNoOutput` before burning. Helpers validates the projected vector
before calling Core and can reject an all-zero quote with
`CoreRedemptionResultMismatch`. Core's exact-output solver instead uses
`InsufficientReserveBalance` or `InsufficientRecoveryShares` when a positive
requested minimum exceeds the available resource. These paths do not imply
one generic reserve-error selector for every Helpers-routed redemption failure.

Compilation, transport/sharing and result projection are separate modules.
Identical calls within the simulation scope can share a physical result.
Consequently a subscriber can observe zero additional physical calls while
still receiving a Helpers-validated observation. A new unshared complete plan
normally issues one Helpers `eth_call`.

The canonical latest pricing path does not require a prior block-header fetch,
final hash verification, SDK pricing, `eth_estimateGas` or a separate
amount-dependent preview after the body is already built. Exploratory SDK
state acquisition and missing Core construction fields are separate work;
they can still incur RPCs while other proposals are measured. The economic
quoter does not actively call the retained amount-dependent Core-preview methods.

SDK jobs and Helpers evaluation currently share eight engine work slots and
the Python event loop. Retained-body replay uses the existing bootstrap
priority lane; initial ordinary proposals use ordinary admission. SDK state
waits release their pricing lease. Independent missing pools/tick requests
are acquired concurrently; a later bitmap continuation can depend on the
preceding simulation result.

Both admission lanes retain FIFO order. A cancelled waiter is removed by its
future identity in constant time, without scanning the lane; a grant cancelled
before its owner resumes returns its permit. The eight-slot limit bounds held
pricing permits. Parked candidate tasks remain owned and are drained when their
producer stops. Completion notifications are registered once per owned task;
completion and released capacity wake the scheduler without rebuilding a wait
set containing every parked candidate. Per-leg admission retains round-robin order.

Candidate banks and SDK payloads retain private mutable pool state. Their
snapshot copier owns the scalar tick/bitmap rows and deep-copies other metadata.
Tick-fill coalescing serializes its already-owned snapshot with the normalized
observation identity without another snapshot copy. Latest search-baseline
coverage is replaced before one owned snapshot copy, preserving the baseline
scalars and independent metadata and coverage rows.
Quick-pass topology descriptors are copied when offered to a consumer; the
ready-list snapshot separately copies mutable origins. A retained single shared
read returns directly without scheduling a timer task. Multi-key reads carry
completed values directly to their original positions and gather only pending
futures. An entirely completed multi-key read retains one cooperative checkpoint.
These changes do not alter simulation inputs, the eight-slot capacity or
shared-read subscriber ownership.

When an AlphaRoutes query closes, its identity is removed and retired before
its owned callbacks are cancelled. That callback cancellation proceeds in the
existing 64-item cooperative quantum, followed by gathering every callback in
chunks with explicit checkpoints. The drain remains owned until complete even
if its caller is cancelled again. Callback outcomes retain their original order;
the closing query keeps its existing outcome handling. The separate worker-stop
path retains its existing cancellation and error ordering.
Each framed callback rechecks its existing query-entry identity at its initial
engine-permit grant. If the query has retired, it
finishes through cancellation before starting fresh SDK pricing. Already-started
SDK work remains owned and drains normally. This closes the gap in which
cooperative cancellation can release slots before every queued callback has
received cancellation. Active-query answers, shared-read ownership and the
eight-permit capacity remain unchanged; no callback/route cap is added.

After all of a closing query's callback writers drain, the existing keep-worker
branch enqueues its complete cancel JSONL frame synchronously. That enqueue does
not acquire the shared active-write lock or await transport backpressure, worker
consumption or acknowledgement. Retired-frame filtering remains until the
reader consumes the acknowledgement or the process stops. Enqueue success is
not physical-stop or delivery proof. Synchronous write errors still stop the
broken shared transport and fan out its ordinary error without replacing the
closing query's outcome. Asynchronous connection-loss detection can occur later
through the existing reader or a later drained write. The last-active
nonterminal query still follows the existing child stop/reap path; active query
and quote-result writes keep their existing lock and drain behavior.

## Step 6: select, publish and display

The Backend quote book ranks complete observations that fit the request. A
new observation of the same funded-route identity replaces that route's prior
observation in either price direction. A concrete whole-plan Helpers disproof
can remove that identity; an ordinary transport or optional SDK failure does
not by itself invalidate its historical observation.
An independently weaker route does not erase a better remaining candidate.
Historical versions do not restore an already superseded current observation.

The publication owner emits the selected whole tuple when it changes, and
emits invalidation if its winner disappears. It retains family observations
for reuse. Origins distinguish discovery providers from the Helpers economic
evaluator; discovery provenance is retained through cache and diagnostics.

The App accepts selected `qualified` frames from the current request owner and
renders their amount, funding, fees and bounds. It can display a stored validated
quote before revalidation or exploration produces another selection. There is
one explicit presentation exception: while refining a historical partial quote
with no observed input limit, an available Backend-requested `fullBudget`
arithmetic estimate can cover that partial quote. It is still an estimate,
not validated full-budget output. A current-search quote, full funding or
observed input limit ends this overlay. It does
not wait for terminal search completion. A new amount or Refresh creates a new
owner; an obsolete owner's late frame cannot overwrite the new intent.

Search can continue improving the result. The streaming flow has no 5 s/15 s
whole-search finish window. A transport ending and an economic quote becoming
usable are different events. Cancellation cleans up owned work; shared reads
can outlive an individual subscriber until their remaining owner work drains.

## Basket differences

Basket issuance (`intent=2`) needs its actual ordered asset/amount vector.
Basket redemption (`intent=3`) can start from CYGLD input before the Basket
display facts arrive. Formatting, resolved view and capture of Basket outputs
still use their real token metadata. Basket edits use their immediate-input
handling rather than the token typing debounce.

## Selection is followed by separate transaction preparation

On selection for execution, the App captures the accepted whole tuple and
stops that selection's refinement. Preparation checks the accepted funding,
minimums, recipient and deployment bindings, replays the selected plan at
`latest` in an unshared Helpers call, then compiles transaction terms. The
existing bootstrap priority covers this selected replay. Wallet signing,
authorization/gas and submission follow in their respective execution flows.
None is a prerequisite for the first displayed quote.

The replay keeps the accepted input maxima and output minima; repricing cannot
relax them. It still uses synthetic-payer simulation funding. Real wallet
balances and authorization, later market/Core state, output minima and
transaction settlement can fail through their ordinary errors after a quote
was observed or prepared.

## Diagnostics describe their own clocks

- Request and producer IDs link shared work without merging subscriber clocks.
- Stage wall/CPU/queue measurements are separate; nested totals overlap.
- An await stage does not sample CPU. In particular, `http.cleanup` measures
  the stream owner's wait for its producer to drain; zero CPU in that row does
  not establish idle time. The narrower `search.cleanup` rows measure the
  simulation-sharing and seed-lookup drains, not every nested search owner.
  Separate closing rows measure Bootstrap owner/provider settlement and
  provider/feed closure, search reconstruction/preparation settlement, and
  shared-read settlement. Synchronous topology and shared-read memo clears
  have CPU rows. These rows preserve the same cancellation ownership, drain
  order, errors and deadlines; inclusive/nested wall totals overlap. They do
  not identify GC, process-wide CPU, scheduling delay or every finalizer.
- The independent event-loop monitor keeps its existing 100 ms sampling and
  lag-event threshold. While its lifecycle is active, a best-effort process GC
  callback observes completed collection spans by generation. Existing lag
  events can include count, wall-span and process-CPU-during-span differences
  since the previous loop measurement, including measurements that emitted no
  log. Immutable cumulative snapshots are never reset by logging. A whole
  collection span is charged when its stop callback is observed; it can cross
  the measurement boundary. Process CPU includes all process threads during
  that callback span and is not exclusive GC function CPU, a quote's CPU, or a
  partition of loop lag. Missing/zero observations do not prove absence of GC.
  No collected-object references or values are retained. The monitor registers
  one owned callback and removes that exact callback on close; ordinary
  observation failures do not replace quote, startup or shutdown behavior.
  GC policy, thresholds, enabled state and scheduling controls remain unchanged;
  no collection is manually triggered. Extra observation allocations may affect
  automatic collection timing, and overhead is unmeasured. No extra timer, log
  gate or quote gate is added.
- `Server-Timing` describes completed work before those response headers. A
  stream header does not include later whole-search work.
- Proxy timings begin inside the Next handler, not at the browser input event.
- The implemented Backend first-executable metric counts its first non-readonly
  `qualified`/`complete` observation, including a stored observation.
- App diagnostics start at the selected flow's loading transition, after token
  debounce and any earlier page prerequisites. Confirmed DOM identifies the
  selected presentation, not its age or a measured browser paint time.
- Backend flow records retain first-occurrence `milestonesMs` for middleware
  entry, headers and first body ready/sent, first selected frame ready/sent,
  disconnect and stream cleanup. These are Backend-local clocks; middleware
  entry does not measure socket arrival or earlier server scheduling. A `sent`
  milestone records completion of the ASGI `send` call, not receipt by a proxy,
  a public client or the browser. Each flow also retains `startedMonotonicMs`,
  its monotonic clock origin, so request milestones and child-flow stage offsets
  can be placed on the same clock within one API process/container lifetime.
  This is not UTC and must not be aligned with a browser or another process/slot
  by assuming a common origin. It distinguishes a sampled acquire before full
  publication from later refinement/cleanup, without proving candidate ownership.
- The stream separately observes the first selected full-budget validated
  non-read-only `qualified`/`complete` frame as `publication.first_full_selected`, with
  `.ready` and `.sent` milestones carried by that exact encoded frame. Full
  budget means its selected funding equals the current canonical request's
  complete ordered currency and raw-amount vector. This is observation metadata,
  not a new result-acceptance, balance, reserve, transaction or display condition.
  First useful validation can still be a limited stored offer. The full-frame
  milestones use the same Backend-local clock and ASGI sent boundary above;
  absence does not establish zero waiting or client receipt.
- Alongside the caller's inclusive `rpc.session` await, completed native
  cache-lock acquisitions retain `rpc.session.acquire`, `rpc.session.executor`, `rpc.session.lock` and
  `rpc.session.resume` queue-kind aggregates. Four readings of the owning flow's
  monotonic clock record executor submission, worker start, lock acquisition
  and the first cache-body membership operation after the acquiring coroutine's
  await resumes. This last boundary includes the few native Python instructions
  before that operation; it is not an exact Future wakeup timestamp.
  Their successive intervals describe executor queuing, blocking lock wait and
  completion/event-loop handoff, not CPU or lock-holder attribution. Only worker
  timestamps cross threads; flow aggregates are updated on the event loop.
  The longest completed `rpc.session.acquire` sample retains one matching
  `acquireBoundariesMs` tuple (`submittedMs`, `workerStartedMs`, `acquiredMs`,
  `cacheEnteredMs`), all offsets from that flow's origin. Independent stage
  maxima may belong to different acquisitions and must not be combined.
  These rows describe completed four-boundary observations; missing/unfinished
  samples do not prove zero delay. Outer `rpc.session` remains inclusive of
  acquisition, cache/session work, replacement/close and other scheduling, with
  its ordinary failure/cancellation accounting. If the caller cancels, that
  outer await ends while its shielded owned lookup can still complete later;
  the completed acquisition rows may extend beyond the cancelled outer span
  and caller elapsed. Nested and parallel totals are not additive critical-path
  time. Diagnostic producer retention can postpone
  the flow record until an already-owned shielded lookup settles, preserving
  caller elapsed and the separate owned-work tail without extending caller waits.
  The native Web3 cache method and per-manager executor/cache remain. Each
  cancellation-safe manager owns a native thread lock shared by its inherited
  synchronous and asynchronous cache methods; unrelated manager caches do not
  serialize through Web3's class-level lock. Native acquire/release, shielded
  ownership and disconnect drain remain. No additional
  acquire, task, timer, retry, capacity limit, deadline or readiness gate is
  introduced. Optional observation failures preserve native results/errors;
  extra observation allocations and scheduling can affect timing, and overhead
  is unmeasured.
- Proxy records separate headers-to-first-downstream-pull from that pull's
  first-read wait, and record upstream cancellation cleanup separately.
- The App's page-local `cybergold:quote-latency` events record native amount edits/Refresh,
  stream dispatch/headers/bytes/parsed selection and the first validated display
  committed to the DOM. Input timing includes debounce. Initial display can use
  the navigation clock. Arithmetic overlays do not count as validated display;
  Refresh retains its clock until the replacement request's selection appears.
  An automatic request restart updates the tracked visible owner even when its
  repeated display event is suppressed. MAX/token-selection changes do not
  restart this measurement.
  These observations send no additional telemetry request and measure no paint.

## Tests

All test suites, including suites run on servers, must leave the public shared
Sandbox fork unchanged throughout setup, execution and cleanup. Public Sandbox
quote and latency checks are read-only and retain their actual observations.

Regular transaction regression profiles exercise mocked browser flows with
synthetic wallet responses, transaction hashes and receipts. They start only a
local App test runtime; they do not start a chain, import wallet secrets, fund
accounts, create real signatures or submit transactions. Mocked quote, balance,
preparation and receipt responses belong to that UI fixture, not to the live
quote-latency cohort. A synthetic pass proves the asserted UI behavior, not
mining, actual balances, protocol reserves, economic settlement or execution
quality. Synthetic hashes and mocked receipts must be identified as such.

Real wallet/chain qualification is a separate explicit opt-in operation, not an
automatic regression profile. Its state-changing setup and execution belong to
an owned disposable fork and attached test runtime. Funding, approvals,
bootstrap purchases and trades must not target the public shared fork. Cleanup
must not reset or revert that fork, including to undo earlier test transactions.
A dedicated wallet alone does not isolate a chain. Sequential real-qualification
cases may share one owned fork whose state evolves; independent cases may
restore their owned baseline. A separate fork per case is not required.
Ordinary real-qualification failures retain their original reasons; mocked
results cannot substitute for that evidence.

Runner implementation and installed selection are recorded separately in the
Ops test workplan. These test contracts change no Backend quote ranking,
Helpers pricing, transaction preparation or current-process diagram.

## Implementation map

Paths below are relative to `python-candidate/src/cybergold_candidate/`.

| Boundary | Implementation |
| --- | --- |
| Progressive stream/cache handoff | `progressive_quotes.py`, `economic_quote_cache.py` |
| Cached arithmetic estimates | `economic_estimate.py`, `quoter/reuse_estimate.py` |
| Scope/generation recovery | `protocol_config.py`, `runtime.py`, `database.py` |
| Backend ranking and publication | `quote_publication.py`, `quoter/quote_book.py`, `quoter/ranking.py` |
| Retained families/reconstruction | `quoter/reuse_routes.py`, `quoter/path_families.py`, `quoter/reuse_estimate.py` |
| Search/initial topology | `quoter/search.py`, `quoter/evaluate.py`, `quoter/discovery.py` |
| Core residual-retention alternative | `quoter/residual_retention.py`, `quoter/search.py` |
| Supplier orchestration/AMM boundary | `quoter/bootstrap.py`, `quoter/providers.py`, `quoter/amm_adapter.py` |
| Local/hosted workers and API pacing | `quoter/alpha_routes.py`, `quoter/hosted_routes.py`, `sdk_worker.py`, `uniswap_api_queue.py` |
| Complete Helpers evaluation | `quoter/plan_call.py`, `quoter/plan_transport.py`, `quoter/plan_simulation.py` |
| Capacity and sharing | `route_work_slots.py`, `shared_reads.py`, `route_quote_engine.py` |
| Core warm state | `quoter/core_state.py`, `app.py` |
| Later execution preparation | `tx_preparation.py` |
| Request and owner observations | `quote_flow.py`, `telemetry.py`, `trade_observation.py` |

App context is implemented in `app/[locale]/page.tsx`,
`app/hooks/flows/quotes/useEconomicQuote.ts`, `app/utils/economicQuoteSearch.ts`,
`app/utils/quoteStream.ts`, `app/server/backend-client.ts` and
`app/server/backend-transport-observation.ts` in the reviewed App revision.
The added page-local latency observations use `app/hooks/useQuoteLatency.ts`
and `app/utils/quoteLatency.ts`, together with the stream and proxy modules above.

## Change history

### 2026-11-08 - Scope HTTP session-cache locking to its manager

- Give each cancellation-safe HTTP session manager its own native thread lock,
  matching its existing independent cache and executor. Both inherited sync and
  async cache operations still use that same manager lock; the Web3 cache body,
  stale-session handling, eviction and HTTP behavior are unchanged.
- Preserve shielded ownership of abandoned lookups, late result/error handling,
  session-acquisition observations and pending-lookup drain before disconnect.
  A manager waiting for its cache lock no longer serializes unrelated managers.
- No RPC concurrency limit, result cache, retry, timeout, deadline, GC policy,
  readiness condition or deployment/test gate changes. Existing process diagrams
  retain the same ownership and delivery dependencies and remain unchanged.

### 2026-11-08 - Observe session acquisition and full-budget stream delivery

- Retain the Backend flow monotonic origin for same-process placement of child
  acquisition samples against request publication; keep UTC/browser clocks separate.
- Observe executor submission, worker start, native lock acquisition and first
  post-await cache-body entry for the same existing session lookup. Add bounded
  queue/lock/handoff aggregates and retain one complete boundary tuple for the
  longest completed acquire, without mixing independent stage maxima.
- Preserve the native Web3 session-cache implementation, shared lock, original
  per-manager executor/cache, cancellation-safe owning task and disconnect drain.
  Retain late diagnostic lookup observations without extending the caller's wait.
- Add separate first full-budget selected/ready/sent milestones on the current
  request and exact encoded frame. Ordered current-request funding equality is
  classification only; limited validated offers and ordinary quote/stream/error
  behavior remain. ASGI send completion does not prove browser receipt.
- No selection, readiness, RPC, concurrency, timeout, deadline, GC, transaction or
  qualification policy changes. Current-process diagrams remain accurate and
  unchanged; these observations add no process dependency or delivery gate.

### 2026-11-08 - Enqueue final calculation retirement without sibling backpressure

- After the existing owned callback drain, enqueue the final complete cancel
  frame without acquiring the shared write lock or awaiting its transport
  drain. A closing query no longer waits at that site for a sibling's blocked
  active write. Keep retired filtering and acknowledgement bookkeeping.
- Preserve active query/result writes, synchronous broken-transport error fanout,
  owned callback settlement and the existing last-active nonterminal child stop.
  Enqueue is not delivery or physical-stop proof; asynchronous transport failure
  can be detected later by the existing reader or a later drained write.
- No background task, route/callback cap, timeout, deadline, GC policy, worker
  protocol or qualification gate is added. Current-process diagrams remain
  accurate and unchanged.

### 2026-11-07 - Avoid discarded tick-fill snapshot copies

- Serialize the already-owned tick-fill snapshot with its normalized observed
  identity without copying that complete snapshot solely for the key.
- Replace latest search-baseline coverage before copying it once with the
  existing scalar-row snapshot copier, rather than copying old coverage and
  immediately overwriting it with recursively copied replacement lists.
- Preserve exact coalescing identity, baseline scalars, metadata and scalar-row
  ownership, fresh latest reads, generations, cancellation and ordinary errors.
  Candidate-bank and SDK-worker payload copies remain. No limits, policies,
  timers or qualification gates change; current-process diagrams remain accurate.

### 2026-11-07 - Stop fresh callback pricing after query retirement

- Carry the framed callback's existing query owner to its initial pricing
  boundary and recheck that exact identity after obtaining an engine permit.
  A retired query cancels there instead of starting fresh SDK arithmetic while
  its other callbacks are still being cooperatively drained.
- Preserve active-query answers, existing eight-permit admission, owned cleanup
  of already-started work, subscriber sharing and ordinary errors. No route or
  callback limit, GC policy, timer, deadline or worker protocol changes.
  Current-process diagrams remain accurate and unchanged.

### 2026-11-07 - Observe process GC callback spans with existing loop lag

- Add best-effort per-generation completed GC callback-span differences to
  existing loop-lag events, using immutable cumulative snapshots and the
  previous loop measurement rather than the previous emitted log row.
- Label wall and process CPU measured during collection spans without claiming
  exclusive GC CPU, a request owner or a causal partition of loop lag. Charge
  whole spans at completion and preserve missing/zero-observation limits.
- Own registration/removal through the existing monitor lifecycle; contain
  ordinary observation failures and retain GC policy/scheduling controls, quote
  behavior, sample/log thresholds and deadlines. Extra observation allocations
  may affect automatic collection timing; overhead is unmeasured.
  Current-process diagrams remain accurate and unchanged.

### 2026-11-07 - Reduce owned quotation bookkeeping and cooperate during callback close

- Replace repeated all-active scheduler waits with completion notifications,
  preserving round-robin feed admission, eight held permits, parked work ownership,
  context-disproof handling and complete cleanup.
- Avoid per-cache-hit timer tasks for multi-key shared reads; preserve original
  positions, pending subscription ownership and one all-cached cooperative checkpoint.
- Cancel and gather retired AlphaRoutes query callbacks in the existing 64-item
  quantum, with an owned drain through repeated caller cancellation. Preserve the
  separate worker-stop path and ordinary result/error handling.
- Current-process diagrams remain accurate: route families, provider dependencies,
  ownership and engine capacity are unchanged. No new cap, deadline or test gate.

### 2026-11-07 - Restore synthetic regular transaction regressions

- Under the owner's explicit authorization, regular transaction profiles return
  to synthetic wallet responses/hashes and mocked receipts, with no funding,
  real signing/submission or fork startup. The App synthetic runner and Ops
  profile dispatch implement this coordinated test behavior.
- Keep live read-only quote/latency evidence separate; synthetic UI outcomes
  establish no mined receipt, balance, reserve or economic-execution proof.
- Keep any real wallet/chain qualification separately opt-in and owned; preserve
  the shared Sandbox no-write boundary. No Backend runtime or diagram change.

### 2026-11-06 - Closing-boundary observations

- Add fixed closing spans for Bootstrap owners/provider feeds, search
  reconstruction/preparation tasks and shared reads, including the shared-read
  close before simulation-sharing cleanup. Measure synchronous clears with
  separate CPU spans.
- Preserve cancellation, owned-task drain order, errors, ranking and deadlines.
  Keep existing `search.cleanup` meaning and independent flow origins; no GC
  or process-wide CPU attribution is introduced.
- Current-process diagrams and source ownership are unchanged.

### 2026-11-05 - Public Sandbox test isolation requirement

- Require all suites, including server-run tests, to leave the public shared
  Sandbox fork unchanged during setup, execution and cleanup.
- Keep state-changing tests on owned disposable forks, with sequential state
  evolution or independent baseline restoration as appropriate.
- Keep ordinary local failures and separate installed-runner compliance from
  this requirement. No Backend runtime or current-process diagram changes.

### 2026-11-05 - Measured Core residual-retention alternative

- Offer one distinct retained-residual body after a generic Core-issuance
  Helpers contract rejection, using the existing owned reconstruction lifecycle.
- Keep input funding, acquisitions, branch allocations, ordinary routed
  exploration and Helpers qualification. No transport retry, typed protocol
  error substitution or selected-plan substitution is introduced.
- Keep explicit empty continuation descriptors through measurement and replay,
  so returned plans disclose retention without claiming residual AMM hops.
- Update diagram 03's issuance label from AMM residuals to residual handling
  and regenerate the linked current-process PDF; diagrams 01 and 02 are unchanged.

### 2026-11-05 - Reuse initial topology across shared query consumers

- Distinguish a registered segment query from an available supplier/completed
  topology offer. Repeated initial whole-plan consumers can reuse the existing
  short prefix instead of waiting for the full custom graph.
- Preserve ready-offer order, query/provider ownership, ordinary later graph
  coverage, Helpers qualification and the existing eight-permit admission.
- Process dependencies and the current-process diagrams are unchanged.

### 2026-11-05 - Streaming controls at each proxy hop

- Set the App's fixed streaming proxy response header independently of the
  upstream header, retaining Backend's existing NDJSON buffering-control header.
- Clarify that proxy controls and completed ASGI sends do not establish public
  flush or client receipt. Performance observations remain in Ops workplans.
- Process dependencies and the current-process diagrams are unchanged.

### 2026-11-05 - Pricing cancellation and qualification boundaries

- Remove cancelled pricing waiters by future identity, preserving ordinary and
  bootstrap FIFO admission, readiness timing, permit return and owned drains.
- Clarify the eight held-permit boundary and the scope of cleanup wall/CPU
  diagnostics. Add focused cancellation, FIFO and eight-owner regressions.
- Clarify synthetic-payer funding, recorded versus current execution, encoded
  Core coverage, distinct supply/minimum/reserve errors and the accepted bounds
  retained by selected-plan replay.
- Process dependencies and the current-process diagrams are unchanged.

### 2026-11-04 - Independent review corrections

- Include initial custom-prefix nominations in supplier candidate counts and
  first-candidate timing, with a regression for the separate lazy-feed counters.
- Keep the App's tracked visible request current after automatic stream restarts
  so a later Refresh waits for its own replacement. Add unit/browser regressions
  and clarify the native-input clock's coverage.

### 2026-11-04 - Authorized latency improvements

- Publish an available in-memory winner before route-seed copies and new search
  scheduling, with a cooperative yield for delivery.
- Try direct/seed-connector topology before the full initial custom graph walk,
  retaining ordinary later routes, ranking and Helpers validation.
- Reduce repeated snapshot/topology copies and timer tasks for retained reads,
  preserving private candidate state and existing shared-work ownership.
- Add Backend send/disconnect/cleanup milestones, proxy pull/cancel timings and
  App input-to-DOM timing that excludes arithmetic overlays.
- Update the affected process diagram and its PDF. The Ops latency workplan
  records authorization, controlled comparisons and qualification; runtime
  performance targets remain there.

### 2026-11-04 - Initial specification

- Document the implemented quotation flow at Backend `8b8a64ac` and the App
  consumer at `1b0bc8d7`, with three current-process diagrams and their PDF.
