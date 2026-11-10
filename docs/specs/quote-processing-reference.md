# Quote processing technical reference

This reference is part of [SPECS.md](../../SPECS.md). It preserves the detailed
implemented contracts behind the quote journey: variant paths, supplier and
worker lifetimes, simulation funding, error handling and diagnostic clocks.
The readable journey and dated observed examples are in SPECS.md. Its history
records changes to both documents and their mirrored implementation.

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

### Funding alternatives after a complete observation

The universal search shares the `{inputs, plan}` proposal representation and
whole-plan evaluation across unused-input reduction, partial-AMM recovery,
direct basket vectors, supply-limited sales and neighboring-budget replay.
Explicit funding edits share acquisition sums, branch allocations and aggregate
funding changes. Neighbor blueprints retain their distinct topology builder for
branch removal, basket ordering, conversion reindexing and redemption aliases.
Weighted allocation, ppm splitting and fee arithmetic retain their own semantics.
Logical native payment and a physical wrapped input remain distinct.

Within one trade, a physical pool can be shared only in the same direction.
The key is the canonical pool identity and physical input token, so aliases
and native wrappers do not create different pools or invert directions.
Its pure projection reuses integer split arithmetic without encoding addresses,
calling the SDK or issuing RPC/API requests.
The common adapter filters crossed split nominations and chooses compatible
conversions against already selected operations. Crossed supplier hints reuse
their union graph through existing discovery to recover shorter alternatives.
One iterator-local memo retains the last completed compatible integer allocation
patterns by total source amount and ordered physical-route identities. Repeated
recoveries bind those patterns to current route/hop representatives and current
origins. No pool data is cached; original compatible weights and the adapter's
ordinary origin-merging deduplication remain unchanged.
An optional continuation without a compatible route keeps its existing
retaining placeholder. Dormant-route enrichment follows the same rule.
Measured quote projection, stored quote publication and fresh preparation
inspect executable templates independently of optional conversion metadata.
Known zero lots are ignored, including receipt-proven zero Core residuals;
unknown Core-produced lots remain potentially funded. A fresh violation uses
the existing specific-error channel with code `opposed-pool-directions` and
the exact pool key. This is a route-selection rule, not a new execution ABI.

For a successful Core purchase, ordered Helpers stages identify consumed Core
inputs `C` and actual residuals `R` by branch and basket asset. This projection
reads the existing `pricingEvidence` stages internally; it adds no public field
and does not subtract aggregate retained charges to guess Core requirements.
Identity acquisitions, native wrappers, zero-weight assets and mixed token
decimals preserve their raw integer amounts.
For identity or zero acquisitions, only the lot changes; their existing body
route and conversion description are preserved. Their canonical nominations
need no priced template and are not offered as route replacements.

Backward target-output pricing nominates source funding for acquisitions of
`C`, or of `C + U` when a nominated market continuation can use a residual `U`.
The first useful-residual proposal reuses each existing continuation's
Helpers-measured `consumedInput` and encoded route. It does not await fresh
residual or primary-market discovery. That `C + U` proposal and pure `C`
funding are offered before their remaining-budget market compositions.
The existing reconstruction owner independently schedules validation of each
novel base proposal, both composition orders and fresh residual exploration.
A pending Helpers call or primary-market discovery does not serialize the
other alternatives. Fresh exploration can still offer a different useful-residual
body and its market combinations. Equivalent proposals share one construction
per order; an oversized base may still produce a fitting recomposition.
The two known sizing calls use the existing bootstrap priority only while
sizing; the scope exits before either proposal is yielded. Their optional
composition construction and fresh residual rerouting use ordinary admission.

First-hop underconsumption supplies a measured source amount; downstream partial
fill uses the existing backward-prefix calculation. A revert remainder alone
does not supply a Core-produced amount. Full-residual exploration remains
available, and useful sibling continuations stay in the changed body.

Measured unused scalar input can be removed when a whole branch consumes zero.
The branch remains at its original index with its routes and metadata intact;
only its explicit funded amount becomes zero. Helpers skips that zero branch.
Aggregate funding must remain positive and smaller than the observed funding.
For a mixed CYGLD sale, the Core redemption lot remains nominal and unchanged;
each market lot uses measured input consumption plus the existing input-side
market fee. Missing conversion evidence leaves that lot unchanged. The changed
complete body is measured again, so removing an unused swap does not assume
its effects on shared pools were neutral.

For one path containing distinct physical pools and no internal native
transition, the existing SDK directly quotes the required output from the
preceding private pool state. There is no original-budget forward diagnostic.
An acquisition with unchanged measured output is reused without SDK work when
its pools are disjoint from every other operation in the changed proposal.
One exact-input replay of a resized path commits its actual forward state;
exact-output quotation does not commit an inverse state.

Helpers measures aggregate conversions rather than individual split paths.
For split paths or internal native transitions, diagnostic SDK replay follows
the selected conversion in execution order with
a private pool bank, obtaining path outputs and pre-swap states. Desired output
is allocated in those observed output proportions; per-hop exact-output pricing
nominates new path inputs `a_i`. Core acquisition sizing directly preserves
those required inputs through ppm encoding. It reserves one ppm for each
positive path, then distributes the remaining ppm proportionally. The final
path retains the integer remainder. For effective shares `p_i`, total funding
is `max(ceil(a_i * 1_000_000 / p_i))` over positive inputs. Every executed path
lot therefore covers its nominated exact-output input, including tiny paths
that ordinary percentage truncation could round to zero.

One replay from the preceding private pool state advances the changed plan;
its returned branch amounts match the actual encoded lots. There is no funding
search or repeated correction. This calculation guarantees input allocation,
not a globally minimal input or target output under changed shared-pool states.
Prefix capacity recovery retains its existing maximum-settleable arithmetic.

Pool fees are already included in SDK pricing. No generic fee is added to the
measured physical Core target; complete Helpers evaluation recomputes all Core,
Helpers and market fees and compares net recipient output. These advisory SDK
calculations do not certify the changed whole plan's output or shared-pool state.

Direct basket issuance can nominate the measured input vector without swaps.
A resized scalar Core body can also be combined with a primary market branch
using remaining original budget. Conversion identities are reindexed with the
body, and both Core-first and market-first orders remain available. Acquisitions
fund only the nominated Core and residual amounts; continuations keep their
existing ABI and operate on the actual runtime residual.

Each root observation owns a finite transformation pass over its existing route
nominees. Derived proposals use the same pass rather than recursively starting
another Core-sizing pass. Within a search, roots are deduplicated by funded-route
identity, measured output/stage evidence and provider revision. A distinct route,
measured result or revision can own another pass. A successful repaired topology
has its own pass; direct funding children remain nonrecursive. Existing proposal identities
deduplicate equivalent bodies and the existing owner cancels and drains its follow-up work. The valid incumbent
is published before optional alternatives. Each complete changed body returns
to the existing Helpers evaluator and quote book; ordinary proposal failure
leaves independent search and the incumbent available.

The phases `core-consumption`, `useful-core-residual` and `core-market-funding`
describe how a candidate was proposed. They do not themselves set
`inputLimitObserved`, establish global capacity, or change output-first ranking.
No iteration cap, zero-retention requirement, new provider predicate or
additional preparation condition beyond the accepted pool-direction rule is introduced.

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
the Python event loop. Retained-body replay, SQL-neighbor candidate calls,
known measured Core-plus-residual and pure-Core sizing, and Helpers calls for
complete funding proposals (including measured unused-input reductions) use
the existing bootstrap priority lane.
Candidate priority ends before recovery, publication callbacks or follow-up
tasks are created. Sizing priority ends before yielding. Fresh route discovery,
residual rerouting, market-composition construction and initial ordinary
proposals retain ordinary admission. Running work is not preempted, and no
lane reserves idle capacity. SDK state waits release their pricing lease.
Independent missing pools/tick requests
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

The economic NDJSON stream emits a blank newline when its next event-queue
wait has been idle for 15 seconds. Empty lines keep HTTP body readers active;
clients ignore them rather than parsing a quote frame. They carry no selected
or full-funding frame metadata. The timeout wraps only `queue.get()`; it does
not cancel the producer, stop search or mark completion. Real queued events
retain their ordinary order, and disconnect retains the existing producer
cancellation and drain ownership.

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

### Retained specialized quote interfaces

The current App form creates input-driven economic requests. The runtime still
constructs `QuoteIntent` for `POST /api/quotes/intent/stream` and for the retained
exact-output/selected-plan branches of `POST /api/quotes/trade/stream`.
With the universal release configured, the direct recipient-less Core endpoint
returns numerical `readOnly` results for modes other than `issue-exact-out`.
Exact-output Core sales can use the specialized solver's solved input to obtain
fresh universal execution bytes with the accepted minima.

These supported interfaces and component diagnostics are retained for deferred
output-target consumers; they are not the ordinary App's exact-input producer.
Its fresh exact-input trade requests and cached economic estimates bypass the
specialized solver. The universal funding workflow reuses inverse arithmetic
without invoking that solver's full preview/qualification pipeline. No public
endpoint, exact-output contract interface or deferred UI mode is retired here.

### Prepare the accepted universal body

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
| Shared funded-plan edits | `quoter/funding.py` |
| Target-output inverse and partial-AMM recovery | `quoter/inverse.py`, `quoter/prefix.py`, `quoter/capacity_recovery.py` |
| Shared pool-direction rule | `quoter/pool_directions.py`, `quoter/amm_adapter.py`, `quoter/plan_simulation.py`, `quoter/quote_book.py` |
| Core consumption and useful residual funding | `quoter/core_funding.py`, `quoter/plan_simulation.py`, `quoter/search.py` |
| Core residual-retention alternative | `quoter/residual_retention.py`, `quoter/search.py` |
| Supplier orchestration/AMM boundary | `quoter/bootstrap.py`, `quoter/providers.py`, `quoter/amm_adapter.py` |
| Local/hosted workers and API pacing | `quoter/alpha_routes.py`, `quoter/hosted_routes.py`, `sdk_worker.py`, `uniswap_api_queue.py` |
| Complete Helpers evaluation | `quoter/plan_call.py`, `quoter/plan_transport.py`, `quoter/plan_simulation.py` |
| Capacity and sharing | `route_work_slots.py`, `shared_reads.py`, `route_quote_engine.py` |
| Core warm state | `quoter/core_state.py`, `app.py` |
| Later execution preparation | `tx_preparation.py` |
| Retained specialized Core quote interfaces | `quote_intent.py`, `trade_quote.py`, `quote_cache.py`, `runtime.py`, `app.py` |
| Request and owner observations | `quote_flow.py`, `telemetry.py`, `trade_observation.py` |

App context is implemented in `app/[locale]/page.tsx`,
`app/hooks/flows/quotes/useEconomicQuote.ts`, `app/utils/economicQuoteSearch.ts`,
`app/utils/quoteStream.ts`, `app/server/backend-client.ts` and
`app/server/backend-transport-observation.ts` in the reviewed App revision.
The added page-local latency observations use `app/hooks/useQuoteLatency.ts`
and `app/utils/quoteLatency.ts`, together with the stream and proxy modules above.
