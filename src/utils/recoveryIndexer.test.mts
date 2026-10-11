import assert from "node:assert/strict";
import test from "node:test";

import {
  buildRecoverySharePortfolio,
  readIndexedRecoveryAssets,
  readIndexedReserveAssets,
  rebuildRecoveryShareBalances,
  type RecoveryQuery,
  type RecoveryTransaction,
} from "../server/onchain-indexer/recoverySharePersistence.ts";
import {
  buildRecoveryPortfolioReadModel,
  materializeRecoverySharePortfolio,
  parseRecoveryPortfolioReadModel,
  RECOVERY_PORTFOLIO_MAX_BALANCES_PER_HOLDER,
} from "../server/onchain-indexer/recoveryPortfolioModel.ts";
import {
  handleRecoverySharesRequest,
  RecoverySharesApiError,
} from "./recoverySharesApi.ts";
import { authorizeIndexerWorker } from "../server/onchain-indexer/workerAuth.ts";

const CORE = "0x00000000000000000000000000000000000000c0";
const OPERATOR = "0x00000000000000000000000000000000000000c3";
const ALICE = "0x00000000000000000000000000000000000000a1";
const BOB = "0x00000000000000000000000000000000000000b2";
const ASSET = "0x0000000000000000000000000000000000000011";
const ZERO = "0x0000000000000000000000000000000000000000";
const SHARE_ID = BigInt(ASSET);
const CONFIG = { chainId: 31_337n, coreAddress: CORE } as const;

type IndexedLog = {
  eventName: string;
  blockNumber: bigint;
  logIndex: number;
  payload: unknown;
};

type StoredBalance = {
  shareId: string;
  holder: string;
  balanceRaw: string;
};

class FakeRecoveryDatabase {
  logs: IndexedLog[] = [];
  balances: StoredBalance[] = [];
  failNextInsert = false;
  private transactionBalances: StoredBalance[] | null = null;

  query: RecoveryQuery = async (sql, params = []) => {
    const statement = sql.replace(/\s+/g, " ").trim();

    if (statement.startsWith("SELECT payload")) {
      const snapshotBlock = BigInt(String(params[2]));
      const eventName = statement.includes("event_name = 'RecoveryActivated'")
        ? "RecoveryActivated"
        : "ReserveLifecycleChanged";
      const rows = this.logs
        .filter(
          (log) =>
            log.eventName === eventName && log.blockNumber <= snapshotBlock
        )
        .map((log) => ({ payload: log.payload }));
      return { rows, rowCount: rows.length };
    }

    if (statement.startsWith("SELECT event_name, payload")) {
      const rows = this.logs
        .filter((log) =>
          ["TransferSingle", "TransferBatch"].includes(log.eventName)
        )
        .sort((left, right) =>
          left.blockNumber === right.blockNumber
            ? left.logIndex - right.logIndex
            : left.blockNumber < right.blockNumber
              ? -1
              : 1
        )
        .map((log) => ({ event_name: log.eventName, payload: log.payload }));
      return { rows, rowCount: rows.length };
    }

    if (statement.startsWith("DELETE FROM onchain_recovery_share_balances")) {
      assert.ok(this.transactionBalances, "share balance deletion must be transactional");
      this.transactionBalances.length = 0;
      return { rows: [], rowCount: 0 };
    }

    if (statement.startsWith("INSERT INTO onchain_recovery_share_balances")) {
      assert.ok(this.transactionBalances, "share balance insertion must be transactional");
      if (this.failNextInsert) {
        this.failNextInsert = false;
        throw new Error("simulated share balance insert failure");
      }
      this.transactionBalances.push({
        shareId: String(params[2]),
        holder: String(params[3]),
        balanceRaw: String(params[4]),
      });
      return { rows: [], rowCount: 1 };
    }

    throw new Error(`Unexpected recovery persistence query: ${statement}`);
  };

  transaction: RecoveryTransaction = async (action) => {
    assert.equal(this.transactionBalances, null, "nested transaction is unsupported");
    const staged = this.balances.map((row) => ({ ...row }));
    this.transactionBalances = staged;
    try {
      const result = await action(this.query);
      this.balances = staged;
      return result;
    } finally {
      this.transactionBalances = null;
    }
  };
}

function singleTransfer(
  blockNumber: bigint,
  logIndex: number,
  from: string,
  to: string,
  id: bigint,
  value: bigint
): IndexedLog {
  return {
    eventName: "TransferSingle",
    blockNumber,
    logIndex,
    payload: { args: { operator: OPERATOR, from, to, id, value } },
  };
}

test("asset-indexed transition events discover zero-share recovery and reserve assets", async () => {
  const database = new FakeRecoveryDatabase();
  database.logs = [
    {
      eventName: "RecoveryActivated",
      blockNumber: 90n,
      logIndex: 0,
      payload: { args: { asset: ASSET } },
    },
    {
      eventName: "RecoveryActivated",
      blockNumber: 110n,
      logIndex: 0,
      payload: { args: { asset: BOB } },
    },
    {
      eventName: "ReserveLifecycleChanged",
      blockNumber: 80n,
      logIndex: 0,
      payload: { args: { asset: ALICE } },
    },
    {
      eventName: "ReserveLifecycleChanged",
      blockNumber: 81n,
      logIndex: 0,
      payload: { args: { asset: ASSET } },
    },
  ];

  const recoveryAssets = await readIndexedRecoveryAssets(CONFIG, 100n, database.query);
  const reserveAssets = await readIndexedReserveAssets(CONFIG, 100n, database.query);

  assert.deepEqual(recoveryAssets, [ASSET]);
  assert.deepEqual(reserveAssets, [ASSET, ALICE]);
});

test("canonical share rebuild merges same-asset cohorts and rolls back failed replacement", async () => {
  const database = new FakeRecoveryDatabase();
  database.balances = [
    { shareId: "99", holder: ALICE, balanceRaw: "500" },
  ];
  database.logs = [
    singleTransfer(10n, 0, ZERO, ALICE, SHARE_ID, 10n),
    {
      eventName: "TransferBatch",
      blockNumber: 11n,
      logIndex: 0,
      payload: {
        args: {
          operator: OPERATOR,
          from: ALICE,
          to: BOB,
          ids: [SHARE_ID],
          values: [4n],
        },
      },
    },
    singleTransfer(12n, 0, ZERO, ALICE, SHARE_ID, 5n),
    singleTransfer(13n, 0, BOB, ZERO, SHARE_ID, 1n),
  ];

  await rebuildRecoveryShareBalances(
    CONFIG,
    database.query,
    database.transaction
  );
  assert.deepEqual(database.balances, [
    { shareId: SHARE_ID.toString(), holder: ALICE, balanceRaw: "11" },
    { shareId: SHARE_ID.toString(), holder: BOB, balanceRaw: "3" },
  ]);

  const canonicalBeforeFailure = structuredClone(database.balances);
  database.logs = [singleTransfer(20n, 0, ZERO, BOB, SHARE_ID, 20n)];
  database.failNextInsert = true;

  await assert.rejects(
    rebuildRecoveryShareBalances(
      CONFIG,
      database.query,
      database.transaction
    ),
    /simulated share balance insert failure/
  );
  assert.deepEqual(database.balances, canonicalBeforeFailure);
});

test("recovery-shares API returns 503 when its pinned Core snapshot is unavailable", async () => {
  const request = new Request(
    `https://example.test/api/recovery/shares?holder=${ALICE}`
  );
  const response = await handleRecoverySharesRequest(request, async () =>
    buildRecoverySharePortfolio({
      config: CONFIG,
      snapshotBlock: 100n,
      balanceRows: [{ share_id: SHARE_ID.toString(), balance_raw: "6" }],
      recovery: null,
    })
  );

  assert.equal(response.status, 503);
  assert.equal(response.headers.get("cache-control"), "no-store");
  assert.deepEqual(await response.json(), {
    error: "Recovery-share RPC snapshot is unavailable",
  });
});

test("recovery-shares API does not reuse a height-only ETag across fork resets", async () => {
  const etag = `W/"recovery-${ALICE.toLowerCase()}-100"`;
  const request = new Request(
    `https://example.test/api/recovery/shares?holder=${ALICE}`,
    { headers: { "If-None-Match": etag } }
  );
  const response = await handleRecoverySharesRequest(request, async () => ({
    enabled: true,
    snapshotBlock: "100",
    balances: [],
    pools: [],
  }));

  assert.equal(response.status, 200);
  assert.equal(response.headers.get("etag"), null);
  assert.equal(response.headers.get("cache-control"), "no-store");
});

test("recovery-shares API exposes shared-limit backpressure without leaking internals", async () => {
  const request = new Request(
    `https://example.test/api/recovery/shares?holder=${ALICE}`
  );
  const response = await handleRecoverySharesRequest(request, async () => {
    throw new RecoverySharesApiError("Recovery-share indexer is busy", 429, 2);
  });

  assert.equal(response.status, 429);
  assert.equal(response.headers.get("retry-after"), "2");
  assert.deepEqual(await response.json(), {
    error: "Recovery-share indexer is busy",
  });
});

test("cached portfolio materialization derives exact cumulative Fund payouts and fails closed", () => {
  const pool = {
    asset: ASSET,
    impaired: true,
  };
  const recovery = {
    collection: CORE,
    pools: [pool],
    fund: {
      configured: true,
      available: true,
      reason: null,
      problem: null,
      governance: OPERATOR,
      governancePaused: false,
      treasury: { deficit: "0" },
      funds: [
        {
          impairedAsset: ASSET,
          generation: "2",
          active: true,
          coverageShares: "100",
          purchasedShares: "20",
          remainingCoverageShares: "80",
          initialCygldCommitment: "80",
          remainingCygldCommitment: "64",
        },
      ],
    },
  };
  const model = buildRecoveryPortfolioReadModel(31_337n, 100n, CORE, recovery as never);
  const portfolio = materializeRecoverySharePortfolio(model, [
    { share_id: SHARE_ID.toString(), balance_raw: "10" },
  ]);
  assert.deepEqual(
    (portfolio.balances[0].fundOffer as { cygldAmount: string }).cygldAmount,
    "8"
  );
  assert.equal(
    (portfolio.balances[0].fundOffer as { governancePaused: boolean })
      .governancePaused,
    false
  );

  recovery.fund.governancePaused = true;
  const globallyPaused = materializeRecoverySharePortfolio(
    buildRecoveryPortfolioReadModel(31_337n, 101n, CORE, recovery as never),
    [{ share_id: SHARE_ID.toString(), balance_raw: "10" }]
  );
  assert.equal(
    (globallyPaused.balances[0].fundOffer as { governancePaused: boolean })
      .governancePaused,
    true
  );

  recovery.fund.governancePaused = false;
  recovery.fund.treasury.deficit = "1";
  const ineligible = materializeRecoverySharePortfolio(
    buildRecoveryPortfolioReadModel(31_337n, 101n, CORE, recovery as never),
    [{ share_id: SHARE_ID.toString(), balance_raw: "10" }]
  );
  assert.equal(
    (ineligible.balances[0].fundOffer as { available: boolean }).available,
    false
  );

  assert.throws(
    () =>
      materializeRecoverySharePortfolio(
        model,
        Array.from(
          { length: RECOVERY_PORTFOLIO_MAX_BALANCES_PER_HOLDER + 1 },
          (_, index) => ({ share_id: String(index + 1), balance_raw: "1" })
        )
      ),
    /cardinality limit/
  );
});

test("cached portfolio schema rejects stale pre-current-state models", () => {
  const current = buildRecoveryPortfolioReadModel(
    31_337n,
    100n,
    CORE,
    null
  );
  assert.equal(parseRecoveryPortfolioReadModel(current), current);
  assert.throws(
    () =>
      parseRecoveryPortfolioReadModel({
        ...current,
        schemaVersion: "3.0",
      }),
    /malformed/
  );

  const recovery = {
    ...current,
    recovery: {
      pools: [],
      fund: {
        status: {
          configured: true,
          available: true,
          reason: null,
          problem: null,
          governance: OPERATOR,
          treasuryDeficit: "0",
        },
        currentFunds: [],
      },
    },
  };
  assert.throws(
    () => parseRecoveryPortfolioReadModel(recovery),
    /malformed/
  );
});

test("internal indexer worker authentication requires a long exact bearer token", () => {
  const token = "t".repeat(32);
  assert.equal(authorizeIndexerWorker(null, ""), "not-configured");
  assert.equal(authorizeIndexerWorker(`Bearer ${token}`, "short"), "not-configured");
  assert.equal(authorizeIndexerWorker("Bearer wrong", token), "invalid");
  assert.equal(authorizeIndexerWorker(`Bearer ${token}`, token), "authorized");
});

test("recovery-shares API joins balances to asset pools rather than events", async () => {
  const request = new Request(
    `https://example.test/api/recovery/shares?holder=${ALICE}`
  );
  const pool = {
    asset: ASSET,
    impaired: false,
    coreAttachedShares: "0",
    externalShares: "9",
    totalShares: "9",
    redeemableRaw: "18",
    cygldPerAssetRawFp18: "1000000000000000000",
    cygldSupplyCap: "0",
    lifecycle: {
      asset: ASSET,
      lifecycle: 0,
      exitEntitlementRaw: "0",
    },
    custody: {
      lifecycle: 0,
      poolImpaired: false,
      redeemablePoolRaw: "18",
      coreAttachedShares: "0",
      externalShares: "9",
      exitEntitlementRaw: "0",
      liveBalanceAvailable: true,
      liveRawCustody: "18",
      activeAvailableRaw: "0",
      poolRawDeficit: "0",
      exitEntitlementDeficitRaw: "0",
    },
  };
  const response = await handleRecoverySharesRequest(request, async () =>
    buildRecoverySharePortfolio({
      config: CONFIG,
      snapshotBlock: 100n,
      balanceRows: [{ share_id: SHARE_ID.toString(), balance_raw: "6" }],
      recovery: { pools: [pool] },
    })
  );

  assert.equal(response.status, 200);
  assert.equal(
    response.headers.get("cache-control"),
    "no-store"
  );
  assert.deepEqual(await response.json(), {
    enabled: true,
    collection: CORE,
    snapshotBlock: "100",
    fund: null,
    balances: [
      {
        shareId: SHARE_ID.toString(),
        balanceRaw: "6",
        pool,
        fundOffer: null,
      },
    ],
    pools: [pool],
  });
});
