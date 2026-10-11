import assert from "node:assert/strict";
import test from "node:test";
import { existsSync, readFileSync } from "node:fs";
import { HttpRequestError, decodeFunctionData, encodeFunctionResult, formatUnits, type Abi, type Address, type Hex } from "viem";
import { CORE_DIAMOND_ABI } from "../contracts/generated/coreDiamond.ts";
import { createRecoveryPortfolioReader, type RecoveryRpcReader } from "../server/recovery/portfolioReader.ts";
import { assertRecoveryPortfolioDeployment, mergeRecoveryPortfolioPages, recoveryActiveBackingLabel, recoverySettlementFailureMessage, type RecoveryPool, type RecoverySharePortfolio } from "./recoveryPortfolio.ts";
import { handleRecoverySharesRequest } from "./recoverySharesApi.ts";
import { recoverySharePayout } from "./recovery.ts";
import { createRecoveryRpcReader } from "../server/recovery/rpcPortfolio.ts";

const addr = (n: number) => `0x${n.toString(16).padStart(40, "0")}` as Address;
const hash = (n: number) => `0x${n.toString(16).padStart(64, "0")}` as Hex;
const ALICE = addr(800), BOB = addr(801), CORE = addr(900);
function pool(asset: Address): RecoveryPool {
  return { asset, impaired: true, coreAttachedShares: "80", externalShares: "20",
    totalShares: "100", redeemableRaw: "0", cygldPerAssetRawFp18: "1000000000000000000",
    cygldSupplyCap: "1000", referenceShares: "100", referenceValueCygld: "100", shareDecimals: 6,
    lifecycle: { asset, lifecycle: 0, exitEntitlementRaw: "0" },
    custody: { lifecycle: 0, poolImpaired: true, redeemablePoolRaw: "0", coreAttachedShares: "80",
      externalShares: "20", exitEntitlementRaw: "0", liveBalanceAvailable: true, liveRawCustody: "45",
      activeAvailableRaw: "0", poolRawDeficit: "0", exitEntitlementDeficitRaw: "0" } };
}
function fake(total = 1) {
  let currentHash = hash(1);
  const calls = { pool: 0, balances: 0, canonical: 0, preview: 0 };
  const assets = Array.from({ length: total }, (_, i) => addr(i + 1));
  const reader: RecoveryRpcReader = {
    chainId: 31338n, core: CORE,
    async block(requested) { return { number: 100n, hash: requested ?? currentHash }; },
    async assertCanonical(block) { calls.canonical++; if (block.hash !== currentHash) throw new Error("Snapshot no longer canonical"); },
    async count() { return BigInt(total); },
    async assets(_block, offset) { const start = Number(offset); return [assets.slice(start, start + 64), BigInt(Math.min(start + 64, total))]; },
    async paused() { return false; },
    async pools(_block, requested) { calls.pool++; return requested.map(pool); },
    async balances(_block, holder, requested) { calls.balances++; return requested.map(() => holder === ALICE ? 10n : 0n); },
    async preview(_block, _asset, shares) { calls.preview++; return shares / 2n; },
    async fund() { return { status: { configured: false, available: false, reason: "not-configured",
      problem: null, governance: null, governancePaused: null }, offers: [] }; },
  };
  return { reader, calls, reset() { currentHash = hash(2); } };
}

test("discovery over 256 positions uses bounded pages with one hash and only publishes complete assembly", async () => {
  const { reader, calls } = fake(300);
  const load = createRecoveryPortfolioReader(reader);
  let portfolio: RecoverySharePortfolio | undefined;
  let offset = 0n;
  let pageCount = 0;
  do {
    const page = await load(ALICE, { offset, blockHash: portfolio?.snapshotBlockHash as Hex | undefined });
    assert.ok(page.pools.length <= 64);
    portfolio = mergeRecoveryPortfolioPages(portfolio, page);
    pageCount++;
    offset = BigInt(page.nextOffset ?? "0");
  } while (!portfolio.complete);
  assert.equal(pageCount, 5);
  assert.equal(portfolio.balances.length, 300);
  assert.equal(portfolio.pools.length, 300);
  assert.equal(calls.pool, 5);
  assert.equal(portfolio.balances[0]?.payoutRaw, "5");
});

test("pool pages are shared, holder balances are isolated, and TTL expiry rereads", async () => {
  const { reader, calls } = fake();
  let now = 0;
  const load = createRecoveryPortfolioReader(reader, () => now);
  await load(ALICE);
  await load(ALICE);
  const bob = await load(BOB);
  assert.equal(bob.balances.length, 0);
  assert.equal(bob.complete, true);
  assert.equal(calls.pool, 1);
  assert.equal(calls.balances, 2);
  assert.equal(calls.canonical, 6);
  now = 10_001;
  await load(ALICE);
  assert.equal(calls.pool, 2);
});

test("same chain, Core and height after Anvil reset do not reuse stale balances", async () => {
  const { reader, calls, reset } = fake(65);
  const load = createRecoveryPortfolioReader(reader);
  const first = await load(ALICE);
  reset();
  await assert.rejects(load(ALICE, { offset: 64n, blockHash: first.snapshotBlockHash as Hex }), /canonical/);
  const restarted = await load(ALICE);
  assert.notEqual(restarted.snapshotBlockHash, first.snapshotBlockHash);
  assert.equal(calls.pool, 2);
  assert.throws(() => mergeRecoveryPortfolioPages(first, restarted), /one snapshot/);
});

test("mid-read reorg fails even when pool and wallet caches existed", async () => {
  const { reader, reset } = fake();
  const load = createRecoveryPortfolioReader(reader);
  await load(ALICE);
  reader.fund = async () => { reset(); throw new Error("optional Fund down"); };
  await assert.rejects(load(ALICE), /canonical/);
});

test("Fund and quote failures preserve proven ownership; observed zero and unreadable custody differ", async () => {
  const { reader } = fake();
  reader.fund = async () => { throw new Error("Do not leak provider credentials"); };
  reader.preview = async () => { throw new Error("preview failed"); };
  const portfolio = await createRecoveryPortfolioReader(reader)(ALICE);
  assert.equal(portfolio.complete, true);
  assert.equal(portfolio.balances[0]?.balanceRaw, "10");
  assert.equal(portfolio.balances[0]?.payoutProblem, "preview-unavailable");
  assert.equal(portfolio.fund?.available, false);
  assert.doesNotMatch(JSON.stringify(portfolio), /credentials/);
  reader.pools = async (_block, assets) => assets.map((asset) => {
    const result = pool(asset); result.custody.liveBalanceAvailable = false; result.custody.liveRawCustody = "0"; return result;
  });
  const unreadable = await createRecoveryPortfolioReader(reader)(ALICE);
  assert.equal(unreadable.balances[0]?.payoutProblem, "custody-unavailable");
  reader.pools = async (_block, assets) => assets.map(pool);
  reader.preview = async () => 0n;
  assert.equal((await createRecoveryPortfolioReader(reader)(ALICE)).balances[0]?.payoutRaw, "0");
});

test("a successful later page cannot hide an earlier optional Fund outage", async () => {
  const { reader } = fake(65);
  const healthy = reader.fund;
  reader.fund = async () => { throw new Error("Fund unavailable"); };
  const load = createRecoveryPortfolioReader(reader);
  const first = await load(ALICE);
  reader.fund = healthy;
  const last = await load(ALICE, { offset: 64n, blockHash: first.snapshotBlockHash as Hex });
  const merged = mergeRecoveryPortfolioPages(first, last);
  assert.equal(merged.complete, true);
  assert.equal(merged.balances.length, 65);
  assert.equal(merged.fund?.configured, true);
  assert.equal(merged.fund?.available, false);
});

test("empty success is complete; partial registry and balance batches fail closed", async () => {
  const empty = await createRecoveryPortfolioReader(fake(0).reader)(ALICE);
  assert.equal(empty.complete, true);
  assert.deepEqual(empty.balances, []);
  const { reader } = fake(3);
  reader.assets = async () => [[addr(1)], 3n];
  await assert.rejects(createRecoveryPortfolioReader(reader)(ALICE), /registry page/);
  const valid = fake(3).reader;
  valid.balances = async () => [];
  await assert.rejects(createRecoveryPortfolioReader(valid)(ALICE), /balance batch/);
});

test("server runtime and browser settlement deployment must describe the same chain and Core", async () => {
  const page = await createRecoveryPortfolioReader(fake().reader)(ALICE);
  assert.doesNotThrow(() => assertRecoveryPortfolioDeployment(page, 31338, CORE));
  assert.throws(() => assertRecoveryPortfolioDeployment(page, 1, CORE), /snapshot chain/);
  assert.throws(() => assertRecoveryPortfolioDeployment(page, 31338, addr(901)), /settlement Core/);
});

test("unconfirmed submission is not reported as a reverted burn; unreadable backing is not zero", () => {
  assert.match(recoverySettlementFailureMessage(true, false), /already have completed/);
  assert.doesNotMatch(recoverySettlementFailureMessage(true, false), /did not burn/);
  assert.match(recoverySettlementFailureMessage(false, false), /does not prove the chain outcome/);
  assert.match(recoverySettlementFailureMessage(true, true), /did not burn/);
  const active = pool(addr(1));
  active.lifecycle.lifecycle = 1;
  active.custody.liveBalanceAvailable = false;
  assert.match(recoveryActiveBackingLabel(active), /Unavailable/);
  active.custody.liveBalanceAvailable = true;
  assert.equal(recoveryActiveBackingLabel(active), "0 asset base units");
});

test("API requires hash-pinned continuation and never exposes upstream errors", async () => {
  const load = createRecoveryPortfolioReader(fake(65).reader);
  const invalid = await handleRecoverySharesRequest(new Request(`https://test/api/recovery/shares?holder=${ALICE}&offset=64`), load);
  assert.equal(invalid.status, 400);
  const page = await handleRecoverySharesRequest(new Request(`https://test/api/recovery/shares?holder=${ALICE}`), load);
  assert.equal(page.status, 200);
  assert.equal(page.headers.get("Cache-Control"), "no-store");
  assert.equal((await page.json()).complete, false);
  const failed = await handleRecoverySharesRequest(new Request(`https://test/api/recovery/shares?holder=${ALICE}`), async () => { throw new Error("secret upstream URL"); });
  assert.equal(failed.status, 503);
  assert.doesNotMatch(await failed.text(), /secret/);
  const throttled = await handleRecoverySharesRequest(new Request(`https://test/api/recovery/shares?holder=${ALICE}`), async () => {
    throw new HttpRequestError({ status: 429, url: "https://secret.test/private", headers: new Headers({ "Retry-After": "45" }) });
  });
  assert.equal(throttled.status, 429);
  assert.equal(throttled.headers.get("Retry-After"), "45");
  assert.doesNotMatch(await throttled.text(), /secret/);
});

test("P-01 immediate payout never sweeps Core participation or excess; native decimal display", () => {
  assert.equal(recoverySharePayout({ impaired: true, redeemableRaw: 0n, liveRawCustody: 45n,
    coreAttachedShares: 80n, externalShares: 10n, shares: 10n }), 5n);
  assert.equal(recoverySharePayout({ impaired: true, redeemableRaw: 0n, liveRawCustody: 120n,
    coreAttachedShares: 0n, externalShares: 20n, shares: 20n }), 20n);
  for (const decimals of [6, 8, 18, 24]) {
    const unit = 10n ** BigInt(decimals);
    assert.equal(formatUnits(20n * unit, decimals), "20");
    assert.equal(recoverySharePayout({ impaired: true, redeemableRaw: 0n, liveRawCustody: 120n * unit,
      coreAttachedShares: 80n * unit, externalShares: 20n * unit, shares: 20n * unit }), 20n * unit);
  }
});

test("Protocol-owned P-01 burn fixtures match App arithmetic; private sibling is not required", () => {
  const local = JSON.parse(readFileSync(new URL("./fixtures/immediate-recovery.json", import.meta.url), "utf8"));
  const source = new URL("../../../cybergold-protocol/packages/1_core/test/fixtures/immediate-recovery.json", import.meta.url);
  if (existsSync(source)) assert.deepEqual(local, JSON.parse(readFileSync(source, "utf8")));
  for (const row of local.impairedBurn) {
    assert.equal(recoverySharePayout({ impaired: true, redeemableRaw: 0n,
      liveRawCustody: BigInt(row.B), coreAttachedShares: BigInt(row.C),
      externalShares: BigInt(row.E), shares: BigInt(row.s) }), BigInt(row.q), row.name);
  }
  for (const row of local.healthyBurn) {
    assert.equal(recoverySharePayout({ redeemableRaw: BigInt(row.L), liveRawCustody: BigInt(row.B),
      externalShares: BigInt(row.E), shares: BigInt(row.s) }), BigInt(row.q), row.name);
  }
});

test("local App / remote Anvil configuration needs no DB or indexer variables", () => {
  const reader = createRecoveryRpcReader({ RPC_URL: "http://127.0.0.1:8545",
    NEXT_PUBLIC_CHAIN_ID: "31338", NEXT_PUBLIC_CORE_DIAMOND_ADDRESS: CORE });
  assert.equal(reader.chainId, 31338n);
  assert.equal(reader.core.toLowerCase(), CORE.toLowerCase());
  assert.throws(() => createRecoveryRpcReader({}), /not configured/);
});

test("real Viem adapter sends hash-pinned RPC calls, batches balances and decodes native ABI without a DB", async () => {
  const seen: string[] = [];
  const asset = addr(1), snapshot = hash(1);
  const authorization = `Bearer ${"a".repeat(64)}`;
  const fetchRpc: typeof fetch = async (_input, init) => {
    assert.equal(init?.redirect, "error");
    assert.equal(String(_input), "https://rpc-fork.cybergold.io/");
    assert.equal(new Headers(init?.headers).get("authorization"), authorization);
    const request = JSON.parse(String(init?.body));
    const answer = (row: { id: number; method: string; params: unknown[] }) => {
      let result: unknown;
      if (row.method === "eth_chainId") result = "0x7a6a"; // 31338
      else if (row.method === "eth_getBlockByNumber" || row.method === "eth_getBlockByHash") {
        result = { number: "0x64", hash: snapshot, timestamp: "0x1", transactions: [], gasLimit: "0x100000", gasUsed: "0x0" };
      } else {
        assert.equal(row.method, "eth_call");
        assert.deepEqual(row.params[1], { blockHash: snapshot, requireCanonical: true });
        const { functionName, args } = decodeFunctionData({ abi: CORE_DIAMOND_ABI, data: (row.params[0] as { data: Hex }).data });
        seen.push(functionName);
        let value: unknown;
        switch (functionName) {
          case "outstandingRecoveryAssetCount": value = 1n; break;
          case "outstandingRecoveryAssets": value = [[asset], 1n]; break;
          case "paused": value = false; break;
          case "balanceOfBatch": assert.deepEqual(args, [[ALICE], [BigInt(asset)]]); value = [10n]; break;
          case "previewRedeemRecoveryShares": value = 4n; break;
          case "recoveryPool": value = { impaired: true, coreAttachedShares: 80n, externalShares: 20n,
            redeemableRaw: 0n, cygldPerAssetRawFp18: 1n, cygldSupplyCap: 1000n,
            referenceShares: 100n, referenceValueCygld: 100n, shareDecimals: 6 }; break;
          case "reserveLifecycle": value = { lifecycle: 0, exitEntitlementRaw: 0n }; break;
          case "reserveCustodyStatus": value = { lifecycle: 0, poolImpaired: true,
            redeemablePoolRaw: 0n, coreAttachedShares: 80n, externalShares: 20n,
            exitEntitlementRaw: 0n, liveBalanceAvailable: true, liveRawCustody: 45n,
            activeAvailableRaw: 0n, poolRawDeficit: 0n, exitEntitlementDeficitRaw: 0n }; break;
          default: throw new Error(`Unexpected read: ${functionName}`);
        }
        result = encodeFunctionResult({ abi: CORE_DIAMOND_ABI as Abi, functionName, result: value });
      }
      return { jsonrpc: "2.0", id: row.id, result };
    };
    return Response.json(Array.isArray(request) ? request.map(answer) : answer(request));
  };
  const reader = createRecoveryRpcReader({ RPC_URL: "https://rpc-fork.cybergold.io/",
    RPC_AUTHORIZATION: authorization, NEXT_PUBLIC_CHAIN_ID: "31338",
    NEXT_PUBLIC_CORE_DIAMOND_ADDRESS: CORE }, fetchRpc);
  const result = await createRecoveryPortfolioReader(reader)(ALICE);
  assert.equal(result.complete, true);
  assert.equal(result.balances[0]?.payoutRaw, "4");
  assert.equal(result.balances[0]?.pool.shareDecimals, 6);
  assert.equal(result.fund?.configured, false);
  assert.ok(seen.includes("balanceOfBatch"));
  assert.equal(seen.filter((name) => name === "recoveryPool").length, 1);
});
