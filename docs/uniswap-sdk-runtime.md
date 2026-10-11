# Uniswap snapshot worker

Python owns RPC, inventory, event reconciliation and cached observations.
The managed Node 26.10.0 JSONL worker receives raw-unit snapshots, quotes or
simulates ordered branches, and reports missing bitmap/tick coverage to Python.
Candidate post-state is isolated from observed state; branches advance shared
pools in execution order. Wire post-state omits unchanged tick coverage.

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
