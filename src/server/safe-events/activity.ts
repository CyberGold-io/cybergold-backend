import { toEventHash, type Hex } from "viem";
import { targetChainId } from "../../config/chain";
import { serverEnv } from "../environment";
import { withTransaction, type TransactionQuery } from "../onchain-indexer/db";
import { configuredSafeHistoryProfileForIndexer, safeExecutionLogArgs } from "./indexer";

type SafeActivityRow = {
  contract_address: string; block_number: string; block_hash: string; tx_hash: string;
  log_index: number; block_timestamp_seconds: string; topics: Hex[]; data: Hex;
};
const executionTopics = new Map([
  [toEventHash("ExecutionSuccess(bytes32,uint256)"), "ExecutionSuccess" as const],
  [toEventHash("ExecutionFailure(bytes32,uint256)"), "ExecutionFailure" as const],
]);

export function decodeSafeActivity(row: SafeActivityRow) {
  const name = executionTopics.get(row.topics[0]);
  // Use the indexer's existing indexed and non-indexed Safe layouts. An unknown
  // event is still visible, but it never becomes a successful execution.
  const args = name ? safeExecutionLogArgs(row) : undefined;
  return { safeAddress: row.contract_address, blockNumber: row.block_number,
    blockHash: row.block_hash, transactionHash: row.tx_hash, logIndex: row.log_index,
    timestampSeconds: row.block_timestamp_seconds, topic: row.topics[0] ?? null,
    eventName: args ? name! : null, safeTxHash: args?.safeTxHash ?? null,
    paymentWei: args?.payment.toString() ?? null };
}

export async function selectSafeActivity(execute: TransactionQuery, chainId: number,
  addresses: readonly string[], lookbackBlocks: bigint) {
  const normalized = addresses.map(address => address.toLowerCase());
  const parameters = [String(chainId), normalized];
  const records = await execute<SafeActivityRow>(`
    SELECT contract_address, block_number::text, block_hash, tx_hash, log_index,
           block_timestamp_seconds::text, topics, data
    FROM onchain_raw_logs WHERE chain_id=$1 AND contract_address=ANY($2::text[])
    ORDER BY block_number DESC, log_index DESC, contract_address ASC LIMIT 101
  `, parameters);
  const coverage = await execute<{ contract_address: string; state_key: string; state_value: string }>(`
    SELECT contract_address, state_key, state_value FROM onchain_sync_state
    WHERE chain_id=$1 AND contract_address=ANY($2::text[])
      AND state_key IN ('raw_log_start_block','raw_log_last_scanned_block',
        'raw_log_last_scanned_block_hash','safe_execution_last_scanned_block')
  `, parameters);
  return { enabled: true as const, chainId, source: "retained-safe-journal" as const,
    // The existing lookback applies to the execution projection. This read view
    // includes older retained rows; it does not move that cursor or backfill RPC.
    projectionLookbackBlocks: lookbackBlocks.toString(),
    coverage: normalized.map(address => {
      const values = new Map(coverage.rows.filter(row => row.contract_address === address)
        .map(row => [row.state_key, row.state_value]));
      return { address, journalStartBlock: values.get("raw_log_start_block") ?? null,
        indexedThroughBlock: values.get("raw_log_last_scanned_block") ?? null,
        indexedThroughBlockHash: values.get("raw_log_last_scanned_block_hash") ?? null,
        projectionIndexedThroughBlock: values.get("safe_execution_last_scanned_block") ?? null };
    }),
    hasMore: records.rows.length > 100, events: records.rows.slice(0, 100).map(decodeSafeActivity) };
}

export async function getSafeActivity() {
  const disabled = { enabled: false as const, events: [] as ReturnType<typeof decodeSafeActivity>[] };
  if (!serverEnv.DATABASE_URL) return disabled;
  const profile = configuredSafeHistoryProfileForIndexer();
  if (!profile.safeAddresses.length) return disabled;
  return withTransaction(async execute => {
    await execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY");
    return selectSafeActivity(execute, targetChainId, profile.safeAddresses, profile.lookbackBlocks);
  });
}
