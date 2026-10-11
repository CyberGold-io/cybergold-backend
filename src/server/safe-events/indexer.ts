import { publicEnv } from "../../config/publicEnvironment.ts";
import { serverEnv } from "../environment.ts";
import { targetChainId } from "@/config/chain";

import {
  createPublicClient,
  decodeAbiParameters,
  getAddress,
  hexToBigInt,
  hexToNumber,
  isAddress,
  toEventHash,
  toHex,
  type Address,
  type Hex,
} from "viem";
import { query, withTransaction } from "@/server/onchain-indexer/db";
import {
  ingestAddressScopedRawLogs,
  prepareRawJournalReplayCoverage,
  rawJournalProjectionReplayEnabled,
  readRawJournalCoverage,
  readRawJournalLogs,
} from "@/server/onchain-indexer/rawLogJournal";
import { shouldSplitDirectProviderLogRequest } from "@/server/onchain-indexer/adaptiveLogPagination";
import {
  normalizeFinalizedRunAnchor,
  planFinalizedProjectionScan,
  selectFinalizedPlanningBoundary,
  type FinalizedRunAnchor,
} from "@/server/onchain-indexer/finalizedReconciliation";
import type { PrivateIndexerGatewayLease } from "@/server/onchain-indexer/gatewayLease";
import { indexerRpcTransport } from "@/server/onchain-indexer/rpcTransport";
import {
  addressScopedRawLogsEnabled,
  type RawBlockHeader,
} from "@/server/onchain-indexer/rawLogModel";
import {
  ADDRESS_SCOPED_TRANSPORT_RETRY_COUNT,
  assertLegacyPerEventDefinitionCount,
  instrumentEthGetLogsRequest,
  type IndexerRpcRequestCounter,
} from "@/server/onchain-indexer/rpcRequestInstrumentation";
import snapshotIdentity from "@/server/onchain-indexer/snapshot-identity.json";

type SafeExecutionStatus = {
  safeTxHash: Hex;
  status: "executed" | "failed";
  transactionHash: Hex;
  blockNumber: string;
  executionDate: string;
};

export class SafeEventApiLimitError extends Error {
  readonly retryAfterSeconds: number;

  constructor(message: string, retryAfterSeconds: number) {
    super(message);
    this.name = "SafeEventApiLimitError";
    this.retryAfterSeconds = retryAfterSeconds;
  }
}

const SAFE_EXECUTION_EVENTS = [
  {
    name: "ExecutionSuccess",
    status: "executed" as const,
    topic: toEventHash("ExecutionSuccess(bytes32,uint256)") as Hex,
  },
  {
    name: "ExecutionFailure",
    status: "failed" as const,
    topic: toEventHash("ExecutionFailure(bytes32,uint256)") as Hex,
  },
] as const;

const SAFE_CURSOR_STATE_KEY = "safe_execution_cursor_version";
const SAFE_CURSOR_BLOCK_HASH_STATE_KEY = "safe_execution_last_scanned_block_hash";
const SAFE_FINALIZED_PROFILE_STATE_KEY = "safe_finalized_projection_profile";
export const SAFE_COMMITTED_FINALIZED_BLOCK_STATE_KEY =
  "safe_committed_finalized_block";
export const SAFE_COMMITTED_FINALIZED_BLOCK_HASH_STATE_KEY =
  "safe_committed_finalized_block_hash";
export const SAFE_COMMITTED_FINALIZED_PROFILE_STATE_KEY =
  "safe_committed_finalized_profile";
export const SAFE_COMMITTED_RECONCILIATION_ID_STATE_KEY =
  "safe_committed_reconciliation_id";
const SAFE_CURSOR_VERSION = snapshotIdentity.safeCursorVersion;
const RAW_JOURNAL_VERSION = snapshotIdentity.rawJournalVersion;

assertLegacyPerEventDefinitionCount("safe", SAFE_EXECUTION_EVENTS.length);

type RpcLog = {
  blockNumber?: Hex | null;
  blockHash?: Hex | null;
  transactionHash?: Hex | null;
  logIndex?: Hex | null;
  data: Hex;
  topics: Hex[];
};

function parseNumberEnv(name: keyof typeof serverEnv, fallback: number) {
  const value = serverEnv[name];
  return value === undefined || Number(value) === 0 ? fallback : Number(value);
}

function boundedNumberEnv(name: keyof typeof serverEnv, fallback: number, maximum: number) {
  return Math.min(parseNumberEnv(name, fallback), maximum);
}

export function configuredSafeAddressesForIndexer() {
  const raw =
    serverEnv.SAFE_EVENT_INDEXER_SAFE_ADDRESSES ??
    serverEnv.SAFE_EVENT_INDEXER_SAFE_ADDRESS ??
    publicEnv.NEXT_PUBLIC_GOVERNANCE_SAFE_ADDRESS ??
    "";
  const addresses = Array.from(
    new Set(
      raw
        .split(",")
        .map((value) => value.trim())
        .filter(Boolean)
        .map((value) => normalizeSafeAddress(value).toLowerCase() as Address)
    )
  );
  if (addresses.length > 16) {
    throw new Error("Safe event indexer address policy exceeds 16 configured Safes");
  }
  return addresses;
}

function getConfig() {
  const rpcUrl =
    serverEnv.ONCHAIN_INDEXER_RPC_URL ??
    serverEnv.RPC_URL ??
    publicEnv.NEXT_PUBLIC_RPC_URL;
  const chainId = BigInt(targetChainId);
  const lookbackBlocks = BigInt(
    boundedNumberEnv("SAFE_EVENT_INDEXER_LOOKBACK_BLOCKS", 50_000, 100_000)
  );
  const chunkBlocks = BigInt(
    boundedNumberEnv("SAFE_EVENT_INDEXER_CHUNK_BLOCKS", 10_000, 10_000)
  );
  const reorgWindow = BigInt(
    boundedNumberEnv("SAFE_EVENT_INDEXER_REORG_WINDOW", 12, 256)
  );
  const maxBlocksPerRun = BigInt(
    boundedNumberEnv("SAFE_EVENT_INDEXER_MAX_BLOCKS_PER_RUN", 20_000, 50_000)
  );
  return {
    rpcUrl,
    chainId,
    lookbackBlocks,
    chunkBlocks,
    reorgWindow,
    maxBlocksPerRun,
    safeAddresses: configuredSafeAddressesForIndexer(),
  };
}

export function configuredSafeHistoryProfileForIndexer() {
  const config = getConfig();
  return Object.freeze({
    safeAddresses: config.safeAddresses,
    lookbackBlocks: config.lookbackBlocks,
    eventSelectors: SAFE_EXECUTION_EVENTS.map((event) => event.topic),
  });
}

function normalizeSafeAddress(value: string): Address {
  if (!isAddress(value)) {
    throw new Error("Invalid Safe address.");
  }
  return getAddress(value);
}

function normalizeSafeTxHashes(values: string[]) {
  return Array.from(
    new Set(
      values
        .filter((value): value is Hex => /^0x[a-fA-F0-9]{64}$/.test(value))
        .map((value) => value.toLowerCase() as Hex)
    )
  );
}

export function safeExecutionLogArgs(log: { topics: readonly Hex[]; data: Hex }) {
  try {
    if (log.topics.length >= 2 && /^0x[a-fA-F0-9]{64}$/.test(log.topics[1])) {
      const [payment] = log.data === "0x" ? [0n] : decodeAbiParameters([{ type: "uint256" }], log.data);
      return {
        safeTxHash: log.topics[1].toLowerCase() as Hex,
        payment,
      };
    }

    if (log.data.length >= 130) {
      const [safeTxHash, payment] = decodeAbiParameters([{ type: "bytes32" }, { type: "uint256" }], log.data);
      return {
        safeTxHash: safeTxHash.toLowerCase() as Hex,
        payment,
      };
    }
  } catch {
    return undefined;
  }

  return undefined;
}

async function deleteIndexedSafeExecutionLogs(
  chainId: bigint,
  safeAddress: Address,
  fromBlock: bigint
) {
  await query(
    `
      DELETE FROM onchain_event_logs
      WHERE chain_id = $1
        AND contract_address = $2
        AND event_name = ANY($3::text[])
        AND block_number >= $4
    `,
    [
      chainId.toString(),
      safeAddress.toLowerCase(),
      SAFE_EXECUTION_EVENTS.map((event) => event.name),
      fromBlock.toString(),
    ]
  );
}

async function persistSafeExecutionLogs(
  chainId: bigint,
  safeAddress: Address,
  logs: Array<{
    eventName: string;
    safeTxHash: Hex;
    blockNumber: bigint;
    blockHash: Hex | null;
    transactionHash: Hex;
    logIndex: number;
    timestamp: bigint;
    payment: bigint;
    topics: readonly Hex[];
    data: Hex;
  }>
) {
  for (const log of logs) {
    await query(
      `
        INSERT INTO onchain_event_logs (
          chain_id,
          contract_address,
          event_name,
          block_number,
          block_hash,
          tx_hash,
          log_index,
          block_timestamp,
          payload
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb)
        ON CONFLICT (chain_id, tx_hash, log_index) DO UPDATE SET
          contract_address = EXCLUDED.contract_address,
          event_name = EXCLUDED.event_name,
          block_number = EXCLUDED.block_number,
          block_hash = EXCLUDED.block_hash,
          block_timestamp = EXCLUDED.block_timestamp,
          payload = EXCLUDED.payload
      `,
      [
        chainId.toString(),
        safeAddress.toLowerCase(),
        log.eventName,
        log.blockNumber.toString(),
        log.blockHash,
        log.transactionHash.toLowerCase(),
        log.logIndex,
        new Date(Number(log.timestamp) * 1000),
        JSON.stringify({
          args: {
            txHash: log.safeTxHash.toLowerCase(),
            payment: log.payment.toString(),
          },
          topics: log.topics,
          data: log.data,
        }),
      ]
    );
  }
}

async function lastScannedSafeBlock(chainId: bigint, safeAddress: Address) {
  const result = await query<{ state_value: string }>(
    `
      SELECT state_value
      FROM onchain_sync_state
      WHERE chain_id = $1
        AND contract_address = $2
        AND state_key = 'safe_execution_last_scanned_block'
      LIMIT 1
    `,
    [chainId.toString(), safeAddress.toLowerCase()]
  );
  if ((result.rowCount ?? 0) !== 1) return null;
  try {
    return BigInt(result.rows[0].state_value);
  } catch {
    return null;
  }
}

async function setLastScannedSafeBlock(
  chainId: bigint,
  safeAddress: Address,
  blockNumber: bigint,
  blockHash?: Hex,
  finalizedProfile?: string
) {
  await withTransaction(async (transactionQuery) => {
    await transactionQuery(
      `
        INSERT INTO onchain_sync_state (
          chain_id,
          contract_address,
          state_key,
          state_value
        ) VALUES ($1, $2, 'safe_execution_last_scanned_block', $3)
        ON CONFLICT (chain_id, contract_address, state_key)
        DO UPDATE SET state_value = EXCLUDED.state_value, updated_at = NOW()
      `,
      [chainId.toString(), safeAddress.toLowerCase(), blockNumber.toString()]
    );
    if (blockHash) {
      await transactionQuery(
        `
          INSERT INTO onchain_sync_state (
            chain_id,
            contract_address,
            state_key,
            state_value
          ) VALUES ($1, $2, $3, $4)
          ON CONFLICT (chain_id, contract_address, state_key)
          DO UPDATE SET state_value = EXCLUDED.state_value, updated_at = NOW()
        `,
        [
          chainId.toString(),
          safeAddress.toLowerCase(),
          SAFE_CURSOR_BLOCK_HASH_STATE_KEY,
          blockHash.toLowerCase(),
        ]
      );
    }
    if (finalizedProfile) {
      await transactionQuery(
        `
          INSERT INTO onchain_sync_state (
            chain_id,
            contract_address,
            state_key,
            state_value
          ) VALUES ($1, $2, $3, $4)
          ON CONFLICT (chain_id, contract_address, state_key)
          DO UPDATE SET state_value = EXCLUDED.state_value, updated_at = NOW()
        `,
        [
          chainId.toString(),
          safeAddress.toLowerCase(),
          SAFE_FINALIZED_PROFILE_STATE_KEY,
          finalizedProfile,
        ]
      );
    }
  });
}

async function lastScannedSafeBlockHash(chainId: bigint, safeAddress: Address) {
  const result = await query<{ state_value: string }>(
    `
      SELECT state_value
      FROM onchain_sync_state
      WHERE chain_id = $1
        AND contract_address = $2
        AND state_key = $3
      LIMIT 1
    `,
    [chainId.toString(), safeAddress.toLowerCase(), SAFE_CURSOR_BLOCK_HASH_STATE_KEY]
  );
  return result.rows[0]?.state_value ?? null;
}

async function finalizedSafeProjectionProfile(
  chainId: bigint,
  safeAddress: Address
) {
  const result = await query<{ state_value: string }>(
    `
      SELECT state_value
      FROM onchain_sync_state
      WHERE chain_id = $1
        AND contract_address = $2
        AND state_key = $3
      LIMIT 1
    `,
    [chainId.toString(), safeAddress.toLowerCase(), SAFE_FINALIZED_PROFILE_STATE_KEY]
  );
  return result.rows[0]?.state_value ?? null;
}

async function committedSafeBoundary(chainId: bigint, safeAddress: Address) {
  const result = await query<{ state_key: string; state_value: string }>(
    `
      SELECT state_key, state_value
      FROM onchain_sync_state
      WHERE chain_id = $1
        AND contract_address = $2
        AND state_key = ANY($3::text[])
    `,
    [
      chainId.toString(),
      safeAddress.toLowerCase(),
      [
        SAFE_COMMITTED_FINALIZED_BLOCK_STATE_KEY,
        SAFE_COMMITTED_FINALIZED_BLOCK_HASH_STATE_KEY,
        SAFE_COMMITTED_FINALIZED_PROFILE_STATE_KEY,
        SAFE_COMMITTED_RECONCILIATION_ID_STATE_KEY,
      ],
    ]
  );
  const values = new Map(
    result.rows.map((row) => [row.state_key, row.state_value])
  );
  let blockNumber: bigint | null = null;
  try {
    const raw = values.get(SAFE_COMMITTED_FINALIZED_BLOCK_STATE_KEY);
    blockNumber = raw === undefined ? null : BigInt(raw);
  } catch {
    blockNumber = null;
  }
  return {
    blockNumber,
    blockHash:
      (values.get(SAFE_COMMITTED_FINALIZED_BLOCK_HASH_STATE_KEY) as Hex | undefined) ??
      null,
    profile:
      values.get(SAFE_COMMITTED_FINALIZED_PROFILE_STATE_KEY) ?? null,
    reconciliationId:
      values.get(SAFE_COMMITTED_RECONCILIATION_ID_STATE_KEY) ?? null,
  };
}

async function ensureSafeCursorVersion(
  chainId: bigint,
  safeAddress: Address
) {
  await query(
    `
      INSERT INTO onchain_sync_state (
        chain_id,
        contract_address,
        state_key,
        state_value
      ) VALUES ($1, $2, $3, $4)
      ON CONFLICT (chain_id, contract_address, state_key) DO NOTHING
    `,
    [
      chainId.toString(),
      safeAddress.toLowerCase(),
      SAFE_CURSOR_STATE_KEY,
      SAFE_CURSOR_VERSION,
    ]
  );
  const result = await query<{ state_value: string }>(
    `
      SELECT state_value
      FROM onchain_sync_state
      WHERE chain_id = $1
        AND contract_address = $2
        AND state_key = $3
      LIMIT 1
    `,
    [chainId.toString(), safeAddress.toLowerCase(), SAFE_CURSOR_STATE_KEY]
  );
  const currentVersion = result.rows[0]?.state_value ?? null;
  if (currentVersion !== null && currentVersion !== SAFE_CURSOR_VERSION) {
    throw new Error(
      `Safe cursor version ${currentVersion} is incompatible with ${SAFE_CURSOR_VERSION}`
    );
  }
  if (currentVersion === null) {
    throw new Error("Safe cursor identity could not be initialized");
  }
}

async function reconcileSafeExecutionEvents(
  safeAddress: Address,
  config: ReturnType<typeof getConfig>,
  rpcRequestCounter: IndexerRpcRequestCounter,
  options?: {
    finalizedAnchor?: FinalizedRunAnchor;
    finalizedProfile?: string;
    gatewayLease?: PrivateIndexerGatewayLease;
    committedReconciliationId?: string | null;
    maximumBlocksPerRun?: bigint;
    beforeGatewayRequest?: () => Promise<void>;
  }
) {
  await ensureSafeCursorVersion(config.chainId, safeAddress);
  const useAddressScopedRawLogs = addressScopedRawLogsEnabled(
    serverEnv.ONCHAIN_INDEXER_ADDRESS_SCOPED_RAW_LOGS
  );
  const useRawJournalReplay = rawJournalProjectionReplayEnabled(
    serverEnv.ONCHAIN_INDEXER_RAW_JOURNAL_REPLAY_ENABLED
  );
  if (
    useRawJournalReplay &&
    (!useAddressScopedRawLogs || !options?.finalizedAnchor)
  ) {
    throw new Error(
      "Safe raw journal replay requires finalized address-scoped reconciliation"
    );
  }
  const client = createPublicClient({
    transport: options?.gatewayLease
      ? options.gatewayLease.createRpcTransport(
        rpcRequestCounter,
        options.beforeGatewayRequest
      )
      : indexerRpcTransport(config.rpcUrl),
  });
  const rawLogClient = useAddressScopedRawLogs
    ? options?.gatewayLease
      ? client
      : createPublicClient({
        transport: indexerRpcTransport(config.rpcUrl, {
          retryCount: ADDRESS_SCOPED_TRANSPORT_RETRY_COUNT,
        }),
      })
    : client;
  const latestBlock = options?.finalizedAnchor
    ? options.finalizedAnchor.blockNumber
    : await client.getBlockNumber();
  const lastScanned = await lastScannedSafeBlock(config.chainId, safeAddress);
  const firstLookback = latestBlock > config.lookbackBlocks ? latestBlock - config.lookbackBlocks : 0n;
  let fromBlock: bigint;
  if (options?.finalizedAnchor) {
    const workingBlockHash = await lastScannedSafeBlockHash(
      config.chainId,
      safeAddress
    );
    const workingFinalizedProfile = await finalizedSafeProjectionProfile(
      config.chainId,
      safeAddress
    );
    const committed = options.gatewayLease
      ? await committedSafeBoundary(config.chainId, safeAddress)
      : {
        blockNumber: null,
        blockHash: null,
        profile: null,
        reconciliationId: null,
      };
    const authenticatedCommitted =
      committed.reconciliationId === options.committedReconciliationId
        ? committed
        : { blockNumber: null, blockHash: null, profile: null };
    const planningBoundary = selectFinalizedPlanningBoundary({
      leaseBound: Boolean(options.gatewayLease),
      working: {
        blockNumber: lastScanned,
        blockHash: workingBlockHash as Hex | null,
        profile: workingFinalizedProfile,
      },
      committed: authenticatedCommitted,
    });
    let canonicalCursorHash: Hex | null = null;
    if (
      planningBoundary.blockNumber !== null &&
      planningBoundary.blockNumber <= latestBlock
    ) {
      if (planningBoundary.blockNumber === latestBlock) {
        canonicalCursorHash = options.finalizedAnchor.blockHash;
      } else {
        const cursorBlock = await client.getBlock({
          blockNumber: planningBoundary.blockNumber,
        });
        const normalizedCursorBlock = normalizeFinalizedRunAnchor({
          number: cursorBlock.number,
          hash: cursorBlock.hash,
        });
        if (
          normalizedCursorBlock.blockNumber !== planningBoundary.blockNumber
        ) {
          throw new Error("Safe cursor header returned the wrong block number");
        }
        canonicalCursorHash = normalizedCursorBlock.blockHash;
      }
    }
    const scanPlan = planFinalizedProjectionScan({
      deploymentStartBlock: firstLookback,
      anchor: options.finalizedAnchor,
      cursor: {
        blockNumber: planningBoundary.blockNumber,
        blockHash: planningBoundary.blockHash,
      },
      canonicalCursorHash,
      reorgWindow: config.reorgWindow,
      forceConfigurationOverlap:
        !options.finalizedProfile ||
        planningBoundary.profile !== options.finalizedProfile,
    });
    if (scanPlan.fromBlock === null) return true;
    fromBlock = scanPlan.fromBlock;
  } else {
    fromBlock =
      lastScanned === null
        ? firstLookback
        : lastScanned > config.reorgWindow
          ? lastScanned - config.reorgWindow
          : 0n;
  }
  const maximumBlocksPerRun = options?.maximumBlocksPerRun ?? config.maxBlocksPerRun;
  const scanToBlock =
    fromBlock + maximumBlocksPerRun - 1n < latestBlock
      ? fromBlock + maximumBlocksPerRun - 1n
      : latestBlock;
  const blockTimestampCache = new Map<bigint, bigint>();
  const indexedLogs: Parameters<typeof persistSafeExecutionLogs>[2] = [];
  const rawBlockHeaderCache = new Map<bigint, RawBlockHeader>();
  const readBlockHeader = async (blockNumber: bigint) => {
    const cached = rawBlockHeaderCache.get(blockNumber);
    if (cached) return cached;
    const block = await client.getBlock({ blockNumber });
    const normalized = normalizeFinalizedRunAnchor({
      number: block.number,
      hash: block.hash,
    });
    if (normalized.blockNumber !== blockNumber) {
      throw new Error("Safe block header returned the wrong block number");
    }
    const header = { hash: normalized.blockHash, timestamp: block.timestamp };
    rawBlockHeaderCache.set(blockNumber, header);
    return header;
  };
  const ingestRawRange = (fromBlock: bigint, toBlock: bigint) =>
    ingestAddressScopedRawLogs({
      chainId: config.chainId,
      address: safeAddress,
      authoritativeStartBlock: firstLookback,
      fromBlock,
      toBlock,
      journalVersion: RAW_JOURNAL_VERSION,
      requestCounter: rpcRequestCounter,
      requestSource: "safe-address",
      shouldSplitRequestFailure: options?.gatewayLease
        ? (error) =>
          options.gatewayLease!.isRangeReductionRequiredError(error)
        : shouldSplitDirectProviderLogRequest,
      requestLogs: (range) =>
        rawLogClient.request({
          method: "eth_getLogs",
          params: [
            {
              address: safeAddress,
              fromBlock: toHex(range.fromBlock),
              toBlock: toHex(range.toBlock),
            },
          ],
        }),
      readBlockHeader,
      blockHeaderCache: rawBlockHeaderCache,
    });
  const ingestRawCoverageRange = async (fromBlock: bigint, toBlock: bigint) => {
    let cursor = fromBlock;
    while (cursor <= toBlock) {
      const chunkEnd =
        cursor + config.chunkBlocks - 1n > toBlock
          ? toBlock
          : cursor + config.chunkBlocks - 1n;
      await ingestRawRange(cursor, chunkEnd);
      cursor = chunkEnd + 1n;
    }
  };
  if (useRawJournalReplay && options?.finalizedAnchor) {
    const existingCoverage = await readRawJournalCoverage({
      chainId: config.chainId,
      address: safeAddress,
      expectedVersion: RAW_JOURNAL_VERSION,
    });
    if (existingCoverage && existingCoverage.startBlock > firstLookback) {
      await ingestRawCoverageRange(
        firstLookback,
        existingCoverage.startBlock - 1n
      );
    }
    if (
      existingCoverage &&
      existingCoverage.startBlock <= firstLookback &&
      existingCoverage.cursorBlock + 1n < firstLookback
    ) {
      await ingestRawCoverageRange(
        existingCoverage.cursorBlock + 1n,
        firstLookback - 1n
      );
    }
  }
  const rawReplayCoverage = options?.finalizedAnchor
    ? await prepareRawJournalReplayCoverage({
      enabled: useRawJournalReplay,
      chainId: config.chainId,
      address: safeAddress,
      expectedVersion: RAW_JOURNAL_VERSION,
      requiredStartBlock: firstLookback,
      maximumBlock: options.finalizedAnchor.blockNumber,
      readBlockHeader,
    })
    : null;
  if (useAddressScopedRawLogs) {
    let cursor = fromBlock;
    while (cursor <= scanToBlock) {
      const toBlock = cursor + config.chunkBlocks - 1n > scanToBlock ? scanToBlock : cursor + config.chunkBlocks - 1n;
      const logs = rawReplayCoverage && toBlock <= rawReplayCoverage.cursorBlock
        ? await readRawJournalLogs({
          chainId: config.chainId,
          address: safeAddress,
          fromBlock: cursor,
          toBlock,
          coverage: rawReplayCoverage,
        })
        : await ingestRawRange(cursor, toBlock);

      for (const log of logs) {
        const event = SAFE_EXECUTION_EVENTS.find(
          (definition) => definition.topic.toLowerCase() === log.topics[0]?.toLowerCase()
        );
        if (!event) continue;
        const decodedArgs = safeExecutionLogArgs({ topics: log.topics, data: log.data });
        if (!decodedArgs) {
          throw new Error(`Failed to decode known ${event.name} Safe raw log`);
        }

        indexedLogs.push({
          eventName: event.name,
          safeTxHash: decodedArgs.safeTxHash,
          blockNumber: log.blockNumber,
          blockHash: log.blockHash,
          transactionHash: log.transactionHash,
          logIndex: log.logIndex,
          timestamp: log.blockTimestampSeconds,
          payment: decodedArgs.payment,
          topics: log.topics,
          data: log.data,
        });
        if (indexedLogs.length > 10_000) {
          throw new Error("Safe event indexer log cardinality exceeds 10,000 entries per run");
        }
      }

      cursor = toBlock + 1n;
    }
  } else {
    for (const event of SAFE_EXECUTION_EVENTS) {
      let cursor = fromBlock;
      while (cursor <= scanToBlock) {
        const toBlock = cursor + config.chunkBlocks - 1n > scanToBlock ? scanToBlock : cursor + config.chunkBlocks - 1n;
        const logs = (await instrumentEthGetLogsRequest(
          rpcRequestCounter,
          "safe-event",
          () =>
            client.request({
              method: "eth_getLogs",
              params: [
                {
                  address: safeAddress,
                  fromBlock: toHex(cursor),
                  toBlock: toHex(toBlock),
                  topics: [event.topic],
                },
              ],
            })
        )) as RpcLog[];

        for (const log of logs) {
          if (!log.blockNumber || !log.transactionHash) continue;
          const decodedArgs = safeExecutionLogArgs({ topics: log.topics, data: log.data });
          if (!decodedArgs) continue;
          const blockNumber = hexToBigInt(log.blockNumber);
          if (!blockTimestampCache.has(blockNumber)) {
            const block = await readBlockHeader(blockNumber);
            blockTimestampCache.set(blockNumber, block.timestamp);
          }
          if (
            options?.finalizedAnchor &&
            (!log.blockHash ||
              log.blockHash.toLowerCase() !==
                (await readBlockHeader(blockNumber)).hash.toLowerCase())
          ) {
            throw new Error("Safe finalized log block hash changed during the run");
          }

          indexedLogs.push({
            eventName: event.name,
            safeTxHash: decodedArgs.safeTxHash,
            blockNumber,
            blockHash: log.blockHash ?? null,
            transactionHash: log.transactionHash,
            logIndex: log.logIndex ? hexToNumber(log.logIndex) : 0,
            timestamp: blockTimestampCache.get(blockNumber) ?? 0n,
            payment: decodedArgs.payment,
            topics: log.topics,
            data: log.data,
          });
          if (indexedLogs.length > 10_000) {
            throw new Error("Safe event indexer log cardinality exceeds 10,000 entries per run");
          }
        }

        cursor = toBlock + 1n;
      }
    }
  }

  const scanToHeader = options?.finalizedAnchor
    ? await readBlockHeader(scanToBlock)
    : null;
  if (
    options?.finalizedAnchor &&
    scanToBlock === options.finalizedAnchor.blockNumber &&
    scanToHeader?.hash.toLowerCase() !==
      options.finalizedAnchor.blockHash.toLowerCase()
  ) {
    throw new Error("Safe projection reached a different finalized anchor hash");
  }
  await deleteIndexedSafeExecutionLogs(config.chainId, safeAddress, fromBlock);
  await persistSafeExecutionLogs(config.chainId, safeAddress, indexedLogs);
  await setLastScannedSafeBlock(
    config.chainId,
    safeAddress,
    scanToBlock,
    scanToHeader?.hash,
    options?.finalizedProfile
  );
  return !options?.finalizedAnchor || scanToBlock === options.finalizedAnchor.blockNumber;
}

export async function reconcileConfiguredSafeExecutionEvents(
  rpcRequestCounter: IndexerRpcRequestCounter,
  options?: {
    finalizedAnchor?: FinalizedRunAnchor;
    finalizedProfile?: string;
    gatewayLease?: PrivateIndexerGatewayLease;
    committedReconciliationId?: string | null;
    maximumBlocksPerRun?: bigint;
    beforeGatewayRequest?: () => Promise<void>;
  }
) {
  const config = getConfig();
  let reachedAnchor = true;
  for (const safeAddress of config.safeAddresses) {
    const safeReachedAnchor = await reconcileSafeExecutionEvents(
      safeAddress,
      config,
      rpcRequestCounter,
      options
    );
    reachedAnchor = reachedAnchor && safeReachedAnchor;
  }
  return reachedAnchor;
}

async function consumeSafeEventRateLimit(scope: string, maximum: number) {
  const windowId = Math.floor(Date.now() / 60_000);
  const result = await query<{ request_count: number }>(
    `
      INSERT INTO onchain_api_rate_limits (scope, window_id, request_count)
      VALUES ($1, $2, 1)
      ON CONFLICT (scope, window_id) DO UPDATE SET
        request_count = onchain_api_rate_limits.request_count + 1,
        updated_at = NOW()
      WHERE onchain_api_rate_limits.request_count < $3
      RETURNING request_count
    `,
    [scope, windowId, maximum]
  );
  if ((result.rowCount ?? 0) === 0) {
    throw new SafeEventApiLimitError(
      "Safe event request rate limit exceeded.",
      Math.max(1, Math.ceil((60_000 - (Date.now() % 60_000)) / 1000))
    );
  }
}

export async function getSafeExecutionStatuses(safeAddressInput: string, safeTxHashInputs: string[]) {
  const safeAddress = normalizeSafeAddress(safeAddressInput);
  if (safeTxHashInputs.length > 64) {
    throw new Error("At most 64 Safe transaction hashes may be queried at once.");
  }
  const safeTxHashes = normalizeSafeTxHashes(safeTxHashInputs);
  if (safeTxHashes.length !== safeTxHashInputs.length) {
    throw new Error("Every Safe transaction hash must be a canonical bytes32 value.");
  }
  if (safeTxHashes.length === 0) return [] as SafeExecutionStatus[];

  const config = getConfig();
  if (!config.safeAddresses.includes(safeAddress.toLowerCase() as Address)) {
    throw new Error("Safe address is outside the configured event-indexer policy.");
  }

  const rateScope = `safe-events:${config.chainId}:${safeAddress.toLowerCase()}`;
  await consumeSafeEventRateLimit(`safe-events:${config.chainId}:global`, 300);
  await consumeSafeEventRateLimit(rateScope, 60);

  const result = await withTransaction(async (transactionQuery) => {
    await transactionQuery("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ");
    await transactionQuery("SET LOCAL statement_timeout = '2000ms'");
    const lock = await transactionQuery<{ slot: number }>(
      `
        SELECT candidate.slot
        FROM generate_series(0, 7) AS candidate(slot)
        WHERE pg_try_advisory_xact_lock(hashtext($1), candidate.slot)
        LIMIT 1
      `,
      [`${rateScope}:concurrency`]
    );
    if ((lock.rowCount ?? 0) === 0) {
      throw new SafeEventApiLimitError("Safe event indexer is busy.", 1);
    }
    return transactionQuery<{
      event_name: string;
      tx_hash: string;
      block_number: string;
      block_timestamp: Date;
      safe_tx_hash: string;
    }>(
      `
        SELECT
          event_name,
          tx_hash,
          block_number,
          block_timestamp,
          payload->'args'->>'txHash' AS safe_tx_hash
        FROM onchain_event_logs
        WHERE chain_id = $1
          AND contract_address = $2
          AND event_name = ANY($3::text[])
          AND payload->'args'->>'txHash' = ANY($4::text[])
        ORDER BY block_number DESC, log_index DESC
      `,
      [
        config.chainId.toString(),
        safeAddress.toLowerCase(),
        SAFE_EXECUTION_EVENTS.map((event) => event.name),
        safeTxHashes,
      ]
    );
  });

  const latestBySafeTxHash = new Map<string, SafeExecutionStatus>();
  for (const row of result.rows) {
    const safeTxHash = row.safe_tx_hash.toLowerCase();
    if (latestBySafeTxHash.has(safeTxHash)) continue;
    latestBySafeTxHash.set(safeTxHash, {
      safeTxHash: safeTxHash as Hex,
      status: row.event_name === "ExecutionFailure" ? "failed" : "executed",
      transactionHash: row.tx_hash as Hex,
      blockNumber: row.block_number,
      executionDate: row.block_timestamp.toISOString(),
    });
  }

  return [...latestBySafeTxHash.values()];
}
