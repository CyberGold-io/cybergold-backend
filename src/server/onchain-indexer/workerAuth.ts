import { serverEnv } from "../environment.ts";
import { timingSafeEqual } from "node:crypto";

const MINIMUM_WORKER_TOKEN_BYTES = 32;

export type WorkerAuthorization = "authorized" | "invalid" | "not-configured";

export function authorizeIndexerWorker(
    authorizationHeader: string | null,
    configuredToken = serverEnv.ONCHAIN_INDEXER_WORKER_TOKEN
): WorkerAuthorization {
    if (!configuredToken || Buffer.byteLength(configuredToken) < MINIMUM_WORKER_TOKEN_BYTES) {
        return "not-configured";
    }
    const prefix = "Bearer ";
    if (!authorizationHeader?.startsWith(prefix)) return "invalid";
    const supplied = Buffer.from(authorizationHeader.slice(prefix.length));
    const expected = Buffer.from(configuredToken);
    return supplied.length === expected.length && timingSafeEqual(supplied, expected)
        ? "authorized"
        : "invalid";
}
