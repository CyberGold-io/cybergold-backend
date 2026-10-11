
import type { Address } from "viem";

import { query } from "./db";

const DASHBOARD_MODEL_KEY = "onchain-dashboard-v1";

type DashboardConfig = {
    chainId: bigint;
    coreAddress: Address;
};

type WriteQuery = (sql: string, params?: unknown[]) => Promise<unknown>;

export async function persistDashboardSnapshot(
    config: DashboardConfig,
    blockNumber: bigint,
    payload: unknown,
    transactionQuery: WriteQuery
) {
    await transactionQuery(
        `
            INSERT INTO onchain_read_model_snapshots (
                chain_id,
                contract_address,
                model_key,
                block_number,
                payload
            ) VALUES ($1, $2, $3, $4, $5::jsonb)
            ON CONFLICT (chain_id, contract_address, model_key, block_number)
            DO UPDATE SET payload = EXCLUDED.payload, created_at = NOW()
        `,
        [
            config.chainId.toString(),
            config.coreAddress.toLowerCase(),
            DASHBOARD_MODEL_KEY,
            blockNumber.toString(),
            JSON.stringify(payload),
        ]
    );
    await transactionQuery(
        `
            DELETE FROM onchain_read_model_snapshots
            WHERE chain_id = $1
              AND contract_address = $2
              AND model_key = $3
              AND block_number > $4
        `,
        [
            config.chainId.toString(),
            config.coreAddress.toLowerCase(),
            DASHBOARD_MODEL_KEY,
            blockNumber.toString(),
        ]
    );
    await transactionQuery(
        `
            DELETE FROM onchain_read_model_snapshots
            WHERE chain_id = $1
              AND contract_address = $2
              AND model_key = $3
              AND block_number NOT IN (
                  SELECT block_number
                  FROM onchain_read_model_snapshots
                  WHERE chain_id = $1
                    AND contract_address = $2
                    AND model_key = $3
                  ORDER BY block_number DESC
                  LIMIT 4
              )
        `,
        [config.chainId.toString(), config.coreAddress.toLowerCase(), DASHBOARD_MODEL_KEY]
    );
}

export async function readCachedDashboardSnapshot(config: DashboardConfig) {
    const result = await query<{ payload: unknown }>(
        `
            SELECT payload
            FROM onchain_read_model_snapshots
            WHERE chain_id = $1
              AND contract_address = $2
              AND model_key = $3
            ORDER BY block_number DESC
            LIMIT 1
        `,
        [config.chainId.toString(), config.coreAddress.toLowerCase(), DASHBOARD_MODEL_KEY]
    );
    if ((result.rowCount ?? 0) !== 1) {
        throw new Error("On-chain dashboard has no completed cached snapshot");
    }
    return result.rows[0].payload;
}
