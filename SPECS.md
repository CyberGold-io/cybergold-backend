# The journey of a quote

This document describes how expressed trading intent becomes a selected,
validated quote and how that quote reaches the App. It follows the quote's
data and dependencies. Preparation for execution and retirement are later
branches of its lifetime.

The description covers implemented behavior. Dated measurements illustrate
that behavior; they are observations, not performance promises or acceptance
conditions. Changes require explicit owner authorization under
[AGENTS.md](AGENTS.md), with coordinated implementation, reference and diagram
updates where affected.

The [technical reference](docs/specs/quote-processing-reference.md) preserves
variant paths, exact error handling, worker ownership, diagnostic clocks and
the implementation map. The current-process diagrams show the same dependencies:
[App to quote](docs/specs/diagrams/01-app-to-quote.svg),
[retained paths and search](docs/specs/diagrams/02-backend-fast-and-search.svg),
and [market and Core paths](docs/specs/diagrams/03-market-and-core.svg).
They are also available as a [three-page process document](output/pdf/quoter-current-process.pdf).

## What changes as the quote progresses

```text
expressed intent → canonical request
                       ├─ fitting stored validated observations ──────────┐
                       └─ retained/new complete plans → Helpers simulation ┤
                                                                        ↓
                                                 selected whole quote, refined over time
                                                                        ↓
                                                 encoded → streamed → parsed → displayed
```

A **route proposal** describes a possible path. A **validated quote** describes
the economic result of a complete plan observed through Helpers simulation.
An **arithmetic estimate** is a separate advisory model result.

A validated quote may allocate less than the request's maximum input budget.
It is then a **limited-budget quote**, but its plan and simulation are complete.
A **full-budget quote** allocates the complete ordered input vector to the plan;
some assets may still be retained rather than exchanged. Neither term says
that exploration is finished, the result is optimal or a real wallet can fund it.
An unallocated part of the request stays outside the plan; an acquired asset
returned by an encoded action is instead a disclosed retained charge.

## 1. Intent becomes a canonical economic request

The App converts the operation direction, input currencies and amounts, and
desired output into one request. Amounts use the tokens' actual decimals and
raw integer units; Basket issuance carries an ordered asset/amount vector.
Configuration supplies the real contract and token identities.

Token typing uses the existing 100 ms debounce before request construction.
Refresh uses the current amount without another typing delay. A cold page may
first need assets, hydration, configuration and token metadata. Those page
prerequisites are separate from the quote request's own lifetime.

The quote request does not depend on a connected wallet, its balances, head
watches or transaction preparation. An independent arithmetic-estimate request
can run alongside it; that response does not validate a trading plan.

**Observed boundary:** native token input to stream dispatch was 165.1–180.1 ms
in the twelve observations described below. This includes App scheduling and
debounce, not just the configured 100 ms delay. Page initialization was not
measured by this interval.

## 2. The request meets retained evidence and new work in parallel

For a scalar request, fitting in-memory validated observations enter the
Backend's quote book first. If one can be selected, it is offered for delivery
before new exploration is scheduled. This path does not await SQL recovery,
SDK pricing or a new Helpers call. The observation retains its original age
and `stored` source; publication does not revalidate it.

Retained route replay, new search and metadata/persisted-history recovery then
progress concurrently. Neighboring amounts and both market/Core route families
can seed new proposals. An optional history failure does not cancel ordinary
search, and persistence need not finish before a selected quote is published.
Basket requests have a separate cache-first entry path.

**Observed boundary:** one of the twelve first full-budget results came from
stored evidence; eleven came from current search. The stored result still
took 1,995.8 ms from input to full-budget DOM. This whole interval is not cache
lookup time: “stored” does not promise immediate delivery.

## 3. Route information becomes complete candidate plans

A retained whole route can be replayed with appropriate funding without
rediscovering its pools. An initial short topology can also construct a complete
plan before detailed SDK amount pricing. Continued exploration supplies other
paths, allocations, splits and residual handling. Each is still a proposal until
the whole plan has an economic observation.

Market legs can draw on five demand-started suppliers: CyberGold discovery,
AlphaRouter, UniRoute local, UniRoute API and GuideStar API. They overlap; they
are not five sequential services every quote must traverse. Their hints feed
the same AMM adapter for market-only and market-plus-Core plans.

A trade may share a physical pool in the same direction. Opposite-direction
use within that trade is excluded. Crossed supplier hints can supply a union
of pools from which existing discovery finds shorter compatible paths. No
additional API request is needed for that reconstruction.

A newly constructed Core operation needs its actual basket construction fields.
An already encoded retained Core plan can proceed without fetching those fields
again. A pure-market plan does not depend on the Core basket basis. A rejected
Core issuance can nominate the implemented residual-retention alternative,
which must receive its own complete Helpers observation.

Funding alternatives use one proposal workflow while keeping their arithmetic
specific to each case. A successful Core purchase supplies measured basket
consumption and each existing continuation's useful input consumption. The
workflow first reuses those measured amounts and encoded continuations to
nominate smaller acquisitions for Core plus the useful residual. It also
offers pure-Core funding before requesting fresh market paths. Backward
exact-output pricing supplies both acquisition proposals; direct basket
issuance uses the measured input vector without acquisition swaps.

Those known proposals can then be combined with a market purchase using the
remaining request budget, in either order. Their validation, both market
compositions and fresh residual-route exploration progress independently;
waiting for one does not serialize the others. Each alternative uses the
same complete-plan evaluation and selection workflow.

Core acquisition sizing uses exact-output SDK prices, including pool fees.
A single path with distinct physical pools is priced directly at the required
output, without replaying its original larger budget. An unchanged measured
acquisition is reused when its pools are independent of all other operations
in the proposal. Internal native transitions and split paths retain the existing
ordered inverse arithmetic.
A direct ceiling calculation funds every encoded path with at least its
required input after percentage rounding. One forward replay advances the
private pool state; complete Helpers simulation measures the recipient's net
output and all applicable fees.

The known Core-plus-residual and pure-Core sizing work uses the existing
bootstrap priority within the shared eight engine permits. Complete funding
proposals use that priority for their Helpers call. These scopes end before
yielding a proposal or starting optional construction. SQL-neighbor priority
also covers only the complete candidate call; its recovery and follow-up work
does not inherit priority. Fresh routing and composition construction keep
ordinary admission, and running work is not preempted.

These amounts are proposals, including their split-path and rounding results.
Each changed complete body returns to Helpers before selection. One root
observation owns a finite pass over its alternatives; derived results do not
recursively start another Core-sizing pass. A distinct funded route, measured
result or provider revision can start further work. A smaller result does not
establish a global input limit or promise that the best spending amount has been found.

**Timing coverage:** the current evidence does not isolate every dependency of
the ultimately selected candidate. Discovery, SDK work, Core reads and replay
overlap. Their totals cannot be summed into a serial “route-building time.”

## 4. Helpers turns a complete plan into a validated observation

The evaluator encodes the whole plan and simulation funding, obtains the existing
engine permission or shares an identical call, then invokes Helpers through
`eth_call` at `latest`. It decodes the result into funded inputs, recipient
outputs, fees, retained charges and bounds. One unshared call normally measures
all encoded market/Core actions in their actual order, including shared-pool
effects; it is not one validation call per route leg.

The projected executable routes must respect the same pool-direction rule.
Receipt-proven zero residuals do not use their dormant routes; unknown amounts
are not treated as zero. This rule also applies to stored quote publication
and fresh transaction preparation. A rejection identifies the opposed pool.

This is a simulation. Funding overrides supply only the synthetic payer's
permitted balances and allowances. Protocol reserves, supply, pools and contract
code retain their ordinary chain state. Protocol shortages and wallet-funding
failures are therefore different questions. A successful simulation does not
prove that a real wallet can authorize or settle the operation later.

Evaluation can wait for shared processing capacity, network responses or
scheduling. Identical reads can share physical work. A measured wait is therefore
not automatically RPC latency. The current evidence does not isolate Helpers
execution time for the selected plan; component timings and exact boundaries
remain in the technical reference and dated Ops evidence.

## 5. Validated observations become one selected whole quote

The Backend compares complete observations whose funding fits the request.
For scalar output it prefers higher output, breaking an equal-output tie with
lower funding. Basket results use comparable output vectors rather than adding
unlike token units. The plan, funding, outputs, fees and bounds remain one tuple;
the App does not select independent provider winners or assemble their legs.

A new observation replaces its own funded route's older observation even when
its price worsens. A concrete Helpers disproof can remove that route. An ordinary
transport/optional SDK failure, or another weaker route, does not by itself erase
a valid remaining observation. If the selected winner changes, another complete
tuple is published; if it disappears without a replacement, it is invalidated.

A useful limited-budget selection may arrive before a full-budget selection.
Further observations can improve or replace either. There is no fixed 5 s/15 s
whole-search finish window, and full-budget funding is not a prerequisite for
publishing a valid limited result.

## 6. The selected quote crosses delivery, parsing and display boundaries

The selected tuple is encoded as a complete newline-delimited JSON record and
passed to the server transport. The App's proxy forwards the stream without
waiting for the search to finish. Both server and streaming proxy request that
their receiving proxy avoid buffering; this control does not prove byte arrival.

While the economic quote stream waits for its next queued event, 15 seconds
without an event produces a blank newline to keep idle HTTP readers active.
Clients ignore that empty line; it carries no quote or completion meaning.
Only the queue wait is timed. Search continues, and disconnect still cancels
and drains the stream's producer through its existing owner.

Network chunks can split a record or contain several records. The browser
accumulates a complete line, parses its JSON, and passes the selected quote to
the current request's consumer. A late frame belonging to an obsolete request
cannot overwrite the current intent. React then commits the accepted quote's
representation to the DOM. Parsing, acceptance, DOM commitment and paint are
different events.

One display exception is explicit: an available full-budget arithmetic estimate
can cover a stored limited quote whose input limit is unknown while refinement
continues. It remains an estimate. A current-search quote, full funding or an
observed input limit ends that overlay. Validated-display timing excludes it.

| Timing term | Exact meaning |
| --- | --- |
| First selected quote parsed | A complete selected JSON record has been decoded, before consumer acceptance/rendering. “Partial” describes its budget coverage, not incomplete JSON or an incomplete plan. |
| First full-budget quote observed in the App | The post-parse selected diagnostic first records full requested funding, immediately before normal consumption. This is the boundary previously called “full result received”; it is not exact socket arrival. |
| First validated display / full-budget display | A current validated representation, limited or full respectively, has committed to DOM. This is before paint and says nothing about funded/enabled Swap readiness. |
| Terminal `complete` message | The stream returns a terminal result. A complete plan or a full-budget `qualified` update can precede it while search continues. |

## 7. The selected quote is captured, replaced or retired

When captured for execution, the accepted whole tuple is frozen and its
refinement stops. Separate preparation replays that selected body at `latest`
through an unshared Helpers call and constructs transaction terms. It preserves
the accepted input maxima and output minima; repricing cannot relax them.
Wallet authorization, signing, gas, submission and settlement follow separately.
Preparation still uses simulation funding, so later wallet, market, reserve or
minimum-output errors remain possible.

A new request or clearing the intent retires the earlier subscription. Its owned
work is cancelled and drained; shared work retains its existing owners. Cleanup
can continue while another quote progresses. It can still interfere through CPU,
the event loop or shared resources, so a long tail is not automatically harmless
or an unconditional barrier. Requesting cancellation does not prove physical
work has stopped; ownership and error details remain in the reference.

**Timing coverage:** this read-only cohort did not measure preparation, signing
or settlement. It did show later full quotes sent before earlier cleanup finished.

## Dated timing example: one quote through these boundaries

On 8 November 2026, twelve read-only built-in-browser observations covered
ETH/PAXG exact-input purchases of CYGLD on Sandbox, Backend `7660b8729f53d7d32a15cd354443ce85b615a50a`
and App `b88239791cd25a79fec122e4b33b15a020353f58`. No cache was flushed;
this is not a controlled cold/warm benchmark. The first four ETH observations
overlapped the automatic live quote profile; later observations shared the host
with synthetic UI work. Sources, contexts and the full population are recorded
in the [dated Ops evidence][observations].

One deliberately identified slow example requested 0.413720 ETH while a PAXG
quote remained active. All following times share that page's clock, starting
at the native input event:

| Quote boundary | Elapsed | Interval from preceding row |
| --- | ---: | ---: |
| Canonical stream request dispatched | 173.8 ms | 173.8 ms |
| Response headers available to JavaScript | 431.7 ms | 257.9 ms |
| First selected limited-budget record parsed | 461.1 ms | 29.4 ms |
| First full-budget selected quote observed | 2,422.1 ms | 1,961.0 ms |
| Full-budget quote representation committed | 2,463.3 ms | 41.2 ms |

The limited-budget quote was already committed at 505.2 ms, a parallel display
milestone between those rows. Full-budget parsing itself completed at 2,422.0 ms;
the selected diagnostic followed at 2,422.1 ms. The 1,961.0 ms interval includes
continued work and delivery; it is not all Helpers execution or JSON parsing.

Across the twelve observations, full-budget DOM ranged from 499.9 to 2,463.3 ms;
the post-parse full-budget observation to DOM interval ranged from 39.5 to
43.9 ms. These endpoints can cover more than one full selection and are not
exclusive render CPU. Backend/proxy timings use separate local clocks and
overlapping work; they cannot be added to this browser partition. Unmeasured
steps remain unmeasured rather than being assigned estimated durations.

## Tests

All suites, including server-run suites, must leave the public shared Sandbox
fork unchanged throughout setup, execution and cleanup. Live quote/latency
checks are read-only and retain their actual observations.

Regular transaction profiles use synthetic wallet responses, hashes and mocked
receipts in a local App runtime. They start no chain, import no wallet secrets,
fund no accounts, create no real signatures and submit no transactions. A pass
proves the asserted UI flow, not real execution, balances, reserves or settlement.

Real chain qualification is a separate explicitly chosen operation on an owned
disposable fork and attached runtime. Its setup, trades and cleanup must never
alter, reset or revert the public fork. Sequential cases may share one evolving
owned fork; independent cases may restore its baseline. A fork per case is not
required. Mocked results cannot replace real-qualification evidence. The reference
preserves the full existing test contract.

[observations]: https://github.com/CyberGold-io/cybergold-ops/blob/da0fc19d2517f772d4b836b8103b08452b71e4e7/docs/work/in-progress/app-ops-validated-quote-latency-workplan-2026-11-04.md#november-8--manager-owned-session-locking-promoted-and-verified

## Change history

<details>
<summary>Dated specification and mirrored implementation changes</summary>

### 2026-11-10 - Direct Core funding and compatible pool directions

- Price a simple physical path directly with exact-output SDK arithmetic;
  reuse an unchanged independent acquisition instead of replaying its larger
  budget. Preserve existing split ceilings, pool fees and final Helpers authority.
- Let funded-proposal validation, both remaining-budget compositions and fresh
  residual exploration run under separate existing task owners. Give a repaired
  route its own finite sizing pass; sizing-only children remain nonrecursive.
- Exclude opposed physical-pool use within one trade while retaining
  same-direction sharing. Rebuild crossed hints using their existing union graph;
  apply the same rule to measured quotes, stored publication and fresh preparation.
- Share integer split weights with route encoding so the pure direction check
  does not repeatedly lower routes or checksum their addresses.
- Update this reference, the technical reference, market/Core diagram and linked
  process PDF together. No iterative amount solver, extra API discovery or new
  execution ABI is introduced.

### 2026-11-09 - Keep idle economic quote streams active

- Emit a blank newline after a 15-second idle event-queue wait, without
  publishing a quote frame or adding a producer/search deadline.
- Preserve selected/full-funding diagnostics, quote arithmetic, ranking,
  ordinary terminal frames and disconnect-owned cancellation/cleanup.
- Update the transport reference; the delivery dependencies shown in the
  current-process diagrams and linked PDF remain unchanged.

### 2026-11-09 - Scope ready Core funding to the existing pricing priority

- Use the existing bootstrap admission lane for measured Core-plus-useful
  residual and pure-Core sizing, and the Helpers calls for complete funding
  proposals, within the unchanged eight engine permits.
- End sizing priority before yielding. Scope SQL-neighbor priority to its
  candidate call so optional follow-up discovery and recovery stay ordinary.
- Preserve ordinary construction, permit cleanup, original input maxima,
  fee arithmetic, proposal evaluation and output-first ranking.

### 2026-11-09 - Offer measured useful funding before fresh market discovery

- Reuse existing Helpers-measured continuation consumption and encoded routes
  to nominate Core-plus-useful-residual funding before optional route discovery.
- Offer that proposal and pure-Core funding before their remaining-budget
  market compositions; retain fresh residual rerouting and its compositions.
- Keep exact-output acquisition sizing, complete Helpers evaluation, ordinary
  proposal failures, input maxima and output-first ranking unchanged.
- Update the technical reference, market/Core diagram and linked process PDF.

### 2026-11-09 - Correct encoded Core acquisition rounding

- Use direct ceiling division over the
  exact-output path inputs and their encoded percentage shares.
- Preserve tiny positive path inputs with a positive share; the final path
  keeps the integer remainder. Replay the resulting acquisition once to advance
  private pool state, then use complete Helpers evaluation for net output/fees.
- Keep fee pricing, quote ranking, prefix arithmetic and ordinary proposal
  failure unchanged; update regressions, technical reference and diagram/PDF.

### 2026-11-09 - Share funding proposals and size acquisitions from Core consumption

- Centralize explicit funded-plan edits for measured unused input, partial-AMM
  recovery, basket vectors and supply-limited sales. Neighboring-budget replay
  retains its topology/ordering builder within the common proposal/evaluation
  workflow.
- Read Core consumption internally from the existing ordered Helpers stages;
  add no public quote field, contract ABI or separate eligibility condition.
- Reuse backward exact-output arithmetic to nominate Core-needed acquisitions,
  useful residual quantities and resized Core/market combinations. Every changed
  body still receives a complete Helpers observation before economic selection.
- Keep each root's transformation pass finite and retain existing cancellation,
  deduplication, error behavior, preparation bounds and output-first ranking.
  Descriptive funding phases do not manufacture observed input-limit evidence.
- Remove the disconnected reconstruction path after moving its economic
  regression and owned-fork qualification consumers onto the active workflow.
  Retain supported exact-output/numeric interfaces and their specialized solver.
- Update the technical reference, implementation map, market/Core diagram and
  linked process PDF with the mirrored implementation.

### 2026-11-08 - Explain the quote journey with dated timing examples

- Reorganize implemented behavior around the quote's transformations, from
  canonical intent through candidate plans, whole-plan observations, selection,
  delivery, consumption and its capture/retirement branches.
- Preserve detailed mechanics and the implementation map in the linked technical
  reference; retain all prior history entries and unchanged current-process diagrams.
- Clarify limited-budget versus complete-plan versus terminal-stream meanings,
  and parsing versus post-parse observation versus DOM/paint boundaries.
- Add source-bound 8 November observations without changing runtime behavior,
  timing contracts, test policy, concurrency, deadlines or acceptance conditions.



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

</details>
