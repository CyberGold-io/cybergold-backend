# Quote processing specifications

This document describes the implemented quotation mechanism. It is not an
improvement proposal or a performance promise. Changes require the owner's
explicit authorization under [AGENTS.md](AGENTS.md), together with the
corresponding implementation and diagram updates.

The initial review describes Backend Dev `8b8a64ac7ce2f0faa46d42653615d2f8aee1c930`.
The App consumer observations describe App Dev
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

## Step 2: consult validated history and start work together

For scalar intents (`0`: token to CYGLD; `1`: CYGLD to token), the Backend:

1. Captures the operation's available local cache scope.
2. Offers fitting exact and neighboring in-memory observations to its quote book.
3. Starts retained-route replay, ordinary search and the publication consumer.
4. Recovers metadata/SQL scope and optional persisted history concurrently.

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
  topology, constructs a whole plan and proceeds to Helpers. This first pass
  deliberately bypasses SDK amount-pricing.
- **Continued exploration:** detailed SDK simulation, alternative allocations,
  router hints, residual handling and repairs propose further complete plans.

Core construction fields are prepared independently. A pure-market proposal
does not need the Core basket basis. A newly constructed Core-containing
proposal needs its real basket assets/weights or output identities to encode
that operation. An already encoded retained Core body goes directly to Helpers
without awaiting those construction fields again. Core
state is warmed independently, cached and invalidated through the implemented
generation/event mechanisms; missing fields are coalesced and independent
reads can run concurrently.

Custom discovery currently walks and sorts its reachable single-path graph
before yielding the first single route. It has cooperative checkpoints, while
split enumeration remains lazy. These are current computation dependencies,
not an assertion that every first route comes from that full graph walk.

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

## Diagnostics describe their own clocks

- Request and producer IDs link shared work without merging subscriber clocks.
- Stage wall/CPU/queue measurements are separate; nested totals overlap.
- `Server-Timing` describes completed work before those response headers. A
  stream header does not include later whole-search work.
- Proxy timings begin inside the Next handler, not at the browser input event.
- The implemented Backend first-executable metric counts its first non-readonly
  `qualified`/`complete` observation, including a stored observation.
- App diagnostics start at the selected flow's loading transition, after token
  debounce and any earlier page prerequisites. Confirmed DOM identifies the
  selected presentation, not its age or a measured browser paint time.

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
| Supplier orchestration/AMM boundary | `quoter/bootstrap.py`, `quoter/providers.py`, `quoter/amm_adapter.py` |
| Local/hosted workers and API pacing | `quoter/alpha_routes.py`, `quoter/hosted_routes.py`, `sdk_worker.py`, `uniswap_api_queue.py` |
| Complete Helpers evaluation | `quoter/plan_call.py`, `quoter/plan_transport.py`, `quoter/plan_simulation.py` |
| Capacity and sharing | `route_work_slots.py`, `shared_reads.py`, `route_quote_engine.py` |
| Core warm state | `quoter/core_state.py`, `app.py` |
| Later execution preparation | `tx_preparation.py` |
| Request and owner observations | `quote_flow.py`, `telemetry.py`, `trade_observation.py` |

App context is implemented in `app/[locale]/page.tsx`,
`app/hooks/flows/quotes/useEconomicQuote.ts`, `app/utils/economicQuoteSearch.ts`,
`app/utils/quoteStream.ts` and `app/server/backend-transport-observation.ts`
in the reviewed App revision.
