import { serverEnv } from "../environment.ts";
import { http } from "viem";

const AUTHORIZATION_HEADER = "ONCHAIN_INDEXER_RPC_AUTHORIZATION";

/**
 * Create the ordinary JSON-RPC transport used by every on-chain indexer.
 *
 * The endpoint itself defines the route: Mainnet uses the private broker and
 * Sandbox uses Anvil.  An optional Authorization header is connection
 * configuration only; it does not select a different indexer execution mode.
 */
export function indexerRpcHeaders(
    authorization = serverEnv.ONCHAIN_INDEXER_RPC_AUTHORIZATION
) {
    if (
        authorization !== undefined &&
        (authorization === "" || /[\r\n\0]/.test(authorization))
    ) {
        throw new Error(`${AUTHORIZATION_HEADER} is invalid`);
    }
    return authorization ? { Authorization: authorization } : undefined;
}

export function indexerRpcTransport(
    url: string,
    options?: Readonly<{ retryCount?: number }>
) {
    return http(url, {
        retryCount: options?.retryCount,
        fetchOptions: { headers: indexerRpcHeaders() },
    });
}
