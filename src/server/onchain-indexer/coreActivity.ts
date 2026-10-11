import { decodeEventLog, parseAbi, type Hex } from "viem";
import { CORE_DIAMOND_ABI } from "../../contracts/generated/coreDiamond";
import { publicEnv } from "../../config/publicEnvironment";
import { targetChainId } from "../../config/chain";
import { serverEnv } from "../environment";
import { withTransaction, type TransactionQuery } from "./db";

// Historical events from Protocol 1b7652c68c8ba8974a7e8320e2910e2a7db14a19.
// Temporary migration facets and initializers are absent from the generated
// live facet ABI. Their receipts remain history, as does LibDiamond ownership.
export const CORE_ACTIVITY_ABI = [
  ...CORE_DIAMOND_ABI.filter(item => item.type === "event"),
  ...parseAbi([
    "event OwnershipTransferred(address indexed previousOwner, address indexed newOwner)",
    "event CoreDiamondCutMigrationArmed(bytes32 indexed commitment, address indexed oldCoordinator, address indexed newCoordinator, address migrationFacet)",
    "event CoreDiamondCutCoordinatorMigrated(bytes32 indexed commitment, address indexed oldCoordinator, address indexed newCoordinator, bytes32 oldRuntimeCodeHash, bytes32 newRuntimeCodeHash, uint64 resultingGeneration, bytes32 manifestHash)",
    "event CoreLegacyFacetRegistryRetired(bytes32 indexed manifestHash, uint256 namespaceCount)",
    "event FacetGenerationUpdated(bytes32 indexed namespace, address indexed incumbent, address indexed candidate, bytes32 oldRuntimeCodeHash, bytes32 newRuntimeCodeHash, uint64 resultingGeneration)",
    "event CoreOptionalInitializerMigrationArmed(bytes32 indexed commitment)",
    "event CoreOptionalInitializerCoordinatorMigrated(bytes32 indexed commitment, address indexed oldCoordinator, address indexed newCoordinator, bytes32 oldRuntimeCodeHash, bytes32 newRuntimeCodeHash, uint64 resultingGeneration)",
  ]),
] as const;

export type CoreActivityRow = {
  block_number: string; block_hash: string; tx_hash: string; log_index: number;
  block_timestamp_seconds: string; topics: Hex[]; data: Hex;
};

export function decodeCoreActivity(row: CoreActivityRow) {
  let eventName: string | null = null;
  let args: Record<string, unknown> | null = null;
  try {
    const event = decodeEventLog({ abi: CORE_ACTIVITY_ABI, topics: row.topics as [Hex, ...Hex[]], data: row.data, strict: true });
    eventName = event.eventName;
    args = JSON.parse(JSON.stringify(event.args, (_key, value) => typeof value === "bigint" ? value.toString() : value));
  } catch { /* Unknown historical versions remain visible as undecoded activity. */ }
  return { blockNumber: row.block_number, blockHash: row.block_hash, transactionHash: row.tx_hash,
    logIndex: row.log_index, timestampSeconds: row.block_timestamp_seconds, topic: row.topics[0] ?? null,
    eventName, arguments: args };
}

export async function selectCoreActivity(execute: TransactionQuery, chainId: number, address: string) {
  const params = [String(chainId), address.toLowerCase()];
  const records = await execute<CoreActivityRow>(`
    SELECT block_number::text, block_hash, tx_hash, log_index,
           block_timestamp_seconds::text, topics, data
    FROM onchain_raw_logs WHERE chain_id=$1 AND contract_address=$2
    ORDER BY block_number DESC, log_index DESC LIMIT 101
  `, params);
  const coverage = await execute<{ state_key: string; state_value: string }>(`
    SELECT state_key, state_value FROM onchain_sync_state
    WHERE chain_id=$1 AND contract_address=$2
      AND state_key IN ('raw_log_start_block','raw_log_last_scanned_block','raw_log_last_scanned_block_hash')
  `, params);
  const state = new Map(coverage.rows.map(row => [row.state_key, row.state_value]));
  return { enabled: true as const, chainId, address: address.toLowerCase(), source: "retained-core-journal" as const,
    journalStartBlock: state.get("raw_log_start_block") ?? null,
    indexedThroughBlock: state.get("raw_log_last_scanned_block") ?? null,
    indexedThroughBlockHash: state.get("raw_log_last_scanned_block_hash") ?? null,
    hasMore: records.rows.length > 100, events: records.rows.slice(0, 100).map(decodeCoreActivity) };
}

export async function getCoreActivity() {
  const address = publicEnv.NEXT_PUBLIC_CORE_DIAMOND_ADDRESS;
  if (!serverEnv.DATABASE_URL || !address) return { enabled: false as const, events: [] as ReturnType<typeof decodeCoreActivity>[] };
  return withTransaction(async execute => {
    await execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY");
    return selectCoreActivity(execute, targetChainId, address);
  });
}
