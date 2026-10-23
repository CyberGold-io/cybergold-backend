import { validatePublicEnvironment } from "../config/publicEnvironment.ts";
import { environmentConfig, environmentSetting, type EnvironmentAddress } from "../config/environmentValidation.ts";

// Private settings stay behind the server-only boundary.
export const serverEnv = environmentConfig({
  CYBERGOLD_RUNTIME_CONFIG_ID: environmentSetting("CYBERGOLD_RUNTIME_CONFIG_ID", () => process.env.CYBERGOLD_RUNTIME_CONFIG_ID, "text"),
  DATABASE_URL: environmentSetting("DATABASE_URL", () => process.env.DATABASE_URL, "database"),
  FORK_FAUCET_ENABLED: environmentSetting("FORK_FAUCET_ENABLED", () => process.env.FORK_FAUCET_ENABLED, "flag"),
  FORK_FAUCET_GENERATION_FILE: environmentSetting("FORK_FAUCET_GENERATION_FILE", () => process.env.FORK_FAUCET_GENERATION_FILE, "text"),
  FORK_FAUCET_RPC_AUTHORIZATION: environmentSetting("FORK_FAUCET_RPC_AUTHORIZATION", () => process.env.FORK_FAUCET_RPC_AUTHORIZATION, "text"),
  FORK_FAUCET_RPC_URL: environmentSetting("FORK_FAUCET_RPC_URL", () => process.env.FORK_FAUCET_RPC_URL, "url"),
  FORK_FAUCET_STATE_ROOT: environmentSetting("FORK_FAUCET_STATE_ROOT", () => process.env.FORK_FAUCET_STATE_ROOT, "text"),
  FORK_FAUCET_HOME: environmentSetting("FORK_FAUCET_HOME", () => process.env.FORK_FAUCET_HOME, "text"),
  FORK_FAUCET_SCRIPT_PATH: environmentSetting("FORK_FAUCET_SCRIPT_PATH", () => process.env.FORK_FAUCET_SCRIPT_PATH, "text"),
  FORK_FAUCET_SERVICE_TOKEN: environmentSetting("FORK_FAUCET_SERVICE_TOKEN", () => process.env.FORK_FAUCET_SERVICE_TOKEN, "text"),
  FORK_FAUCET_SERVICE_URL: environmentSetting("FORK_FAUCET_SERVICE_URL", () => process.env.FORK_FAUCET_SERVICE_URL, "url"),
  FOUNDRY_BIN_DIR: environmentSetting("FOUNDRY_BIN_DIR", () => process.env.FOUNDRY_BIN_DIR, "text"),
  ONCHAIN_CYGLD_REF_CACHE_TTL_MS: environmentSetting("ONCHAIN_CYGLD_REF_CACHE_TTL_MS", () => process.env.ONCHAIN_CYGLD_REF_CACHE_TTL_MS, "integer"),
  ONCHAIN_INDEXER_ADDRESS_SCOPED_RAW_LOGS: environmentSetting("ONCHAIN_INDEXER_ADDRESS_SCOPED_RAW_LOGS", () => process.env.ONCHAIN_INDEXER_ADDRESS_SCOPED_RAW_LOGS, "flag"),
  ONCHAIN_INDEXER_ARCHIVE_FREE_FINALIZED_MODE: environmentSetting("ONCHAIN_INDEXER_ARCHIVE_FREE_FINALIZED_MODE", () => process.env.ONCHAIN_INDEXER_ARCHIVE_FREE_FINALIZED_MODE, "flag"),
  ONCHAIN_INDEXER_CHUNK_SIZE: environmentSetting("ONCHAIN_INDEXER_CHUNK_SIZE", () => process.env.ONCHAIN_INDEXER_CHUNK_SIZE, "integer"),
  ONCHAIN_INDEXER_FINALIZED_MULTICALL_ENABLED: environmentSetting("ONCHAIN_INDEXER_FINALIZED_MULTICALL_ENABLED", () => process.env.ONCHAIN_INDEXER_FINALIZED_MULTICALL_ENABLED, "flag"),
  ONCHAIN_INDEXER_MAX_BLOCKS_PER_RUN: environmentSetting("ONCHAIN_INDEXER_MAX_BLOCKS_PER_RUN", () => process.env.ONCHAIN_INDEXER_MAX_BLOCKS_PER_RUN, "integer"),
  ONCHAIN_INDEXER_RAW_JOURNAL_REPLAY_ENABLED: environmentSetting("ONCHAIN_INDEXER_RAW_JOURNAL_REPLAY_ENABLED", () => process.env.ONCHAIN_INDEXER_RAW_JOURNAL_REPLAY_ENABLED, "flag"),
  ONCHAIN_INDEXER_RECONCILE_INTERVAL_MS: environmentSetting("ONCHAIN_INDEXER_RECONCILE_INTERVAL_MS", () => process.env.ONCHAIN_INDEXER_RECONCILE_INTERVAL_MS, "integer"),
  ONCHAIN_INDEXER_RECOVERY_SHARE_V2_ENABLED: environmentSetting("ONCHAIN_INDEXER_RECOVERY_SHARE_V2_ENABLED", () => process.env.ONCHAIN_INDEXER_RECOVERY_SHARE_V2_ENABLED, "flag"),
  ONCHAIN_INDEXER_REORG_WINDOW: environmentSetting("ONCHAIN_INDEXER_REORG_WINDOW", () => process.env.ONCHAIN_INDEXER_REORG_WINDOW, "integer"),
  ONCHAIN_INDEXER_RPC_AUTHORIZATION: environmentSetting("ONCHAIN_INDEXER_RPC_AUTHORIZATION", () => process.env.ONCHAIN_INDEXER_RPC_AUTHORIZATION, "text"),
  ONCHAIN_INDEXER_RPC_GATEWAY_ENABLED: environmentSetting("ONCHAIN_INDEXER_RPC_GATEWAY_ENABLED", () => process.env.ONCHAIN_INDEXER_RPC_GATEWAY_ENABLED, "flag"),
  ONCHAIN_INDEXER_RPC_GATEWAY_TOKEN: environmentSetting("ONCHAIN_INDEXER_RPC_GATEWAY_TOKEN", () => process.env.ONCHAIN_INDEXER_RPC_GATEWAY_TOKEN, "text"),
  ONCHAIN_INDEXER_RPC_URL: environmentSetting("ONCHAIN_INDEXER_RPC_URL", () => process.env.ONCHAIN_INDEXER_RPC_URL, "url"),
  ONCHAIN_INDEXER_START_BLOCK: environmentSetting("ONCHAIN_INDEXER_START_BLOCK", () => process.env.ONCHAIN_INDEXER_START_BLOCK, "integer"),
  ONCHAIN_INDEXER_WORKER_TOKEN: environmentSetting("ONCHAIN_INDEXER_WORKER_TOKEN", () => process.env.ONCHAIN_INDEXER_WORKER_TOKEN, "text"),
  RPC_AUTHORIZATION: environmentSetting("RPC_AUTHORIZATION", () => process.env.RPC_AUTHORIZATION, "text"),
  RPC_URL: environmentSetting("RPC_URL", () => process.env.RPC_URL, "url"),
  SAFE_EVENT_INDEXER_CHUNK_BLOCKS: environmentSetting("SAFE_EVENT_INDEXER_CHUNK_BLOCKS", () => process.env.SAFE_EVENT_INDEXER_CHUNK_BLOCKS, "integer"),
  SAFE_EVENT_INDEXER_LOOKBACK_BLOCKS: environmentSetting("SAFE_EVENT_INDEXER_LOOKBACK_BLOCKS", () => process.env.SAFE_EVENT_INDEXER_LOOKBACK_BLOCKS, "integer"),
  SAFE_EVENT_INDEXER_MAX_BLOCKS_PER_RUN: environmentSetting("SAFE_EVENT_INDEXER_MAX_BLOCKS_PER_RUN", () => process.env.SAFE_EVENT_INDEXER_MAX_BLOCKS_PER_RUN, "integer"),
  SAFE_EVENT_INDEXER_REORG_WINDOW: environmentSetting("SAFE_EVENT_INDEXER_REORG_WINDOW", () => process.env.SAFE_EVENT_INDEXER_REORG_WINDOW, "integer"),
  SAFE_EVENT_INDEXER_SAFE_ADDRESS: environmentSetting<EnvironmentAddress>("SAFE_EVENT_INDEXER_SAFE_ADDRESS", () => process.env.SAFE_EVENT_INDEXER_SAFE_ADDRESS, "address"),
  SAFE_EVENT_INDEXER_SAFE_ADDRESSES: environmentSetting("SAFE_EVENT_INDEXER_SAFE_ADDRESSES", () => process.env.SAFE_EVENT_INDEXER_SAFE_ADDRESSES, "addresses"),
  SAFE_TX_SERVICE_URL: environmentSetting("SAFE_TX_SERVICE_URL", () => process.env.SAFE_TX_SERVICE_URL, "url"),
});

export function validateEnvironment() {
  validatePublicEnvironment();
  Object.values(serverEnv);
}
