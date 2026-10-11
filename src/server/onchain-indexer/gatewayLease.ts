import { http, type Hex } from "viem";

import {
    normalizeFinalizedRunAnchor,
    type FinalizedRunAnchor,
} from "./finalizedReconciliation.ts";
import {
    IndexerGatewayRpcMethodRejectedError,
    type IndexerRpcRequestCounter,
} from "./rpcRequestInstrumentation.ts";

export const INDEXER_GATEWAY_RPC_PATH = "/rpc/indexer";
export const INDEXER_GATEWAY_LEASE_ACQUIRE_PATH = "/rpc/indexer/leases";
export const INDEXER_GATEWAY_LEASE_RELEASE_PATH =
    "/rpc/indexer/leases/release";
export const INDEXER_GATEWAY_LEASE_TOKEN_HEADER =
    "X-CyberGold-RPC-Lease";
export const INDEXER_GATEWAY_RECONCILIATION_HEADER =
    "X-CyberGold-RPC-Reconciliation";
export const INDEXER_GATEWAY_CONTRACT_VERSION = 1;
export const INDEXER_GATEWAY_LEASE_ACQUIRE_CONTRACT_VERSION = 2;

const MAXIMUM_LEASE_CONTRACT_BYTES = 4_096;
const GATEWAY_REQUEST_TIMEOUT_MS = 35_000;
const GATEWAY_RPC_CONCURRENCY = 4;
const RECONCILIATION_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
const LEASE_TOKEN_PATTERN = /^[A-Za-z0-9_-]{43,128}$/;
const CONFIG_REVISION_PATTERN = /^[0-9a-f]{64}$/;
const HASH_PATTERN = /^0x[0-9a-f]{64}$/;

export type IndexerGatewayLeaseExpectation = Readonly<{
    reconciliationId: string;
    expectedRuntimeRevision: string;
    expectedFinalizedAnchor: FinalizedRunAnchor;
}>;

type FetchFunction = typeof fetch;

type GatewayDependencies = Readonly<{
    fetch?: FetchFunction;
    now?: () => number;
}>;

export type IndexerGatewayEnvironment = Readonly<{
    ONCHAIN_INDEXER_RPC_GATEWAY_ENABLED?: string;
    ONCHAIN_INDEXER_RPC_URL?: string;
    ONCHAIN_INDEXER_RPC_GATEWAY_TOKEN?: string;
}>;

export class IndexerGatewayLeaseError extends Error {
    constructor() {
        super("Indexer gateway lease restart required");
        this.name = "IndexerGatewayLeaseError";
    }
}

export class IndexerGatewayRangeReductionRequiredError extends Error {
    constructor() {
        super("Indexer gateway log range reduction required");
        this.name = "IndexerGatewayRangeReductionRequiredError";
    }
}

export function indexerGatewayHealthIsSuppressed(input: {
    activeReconciliationId: string | null;
    ambiguousUntilMs: number;
    nowMs: number;
}) {
    if (input.activeReconciliationId === null) return false;
    return (
        !Number.isSafeInteger(input.ambiguousUntilMs) ||
        !Number.isSafeInteger(input.nowMs) ||
        input.nowMs < input.ambiguousUntilMs
    );
}

function booleanFlag(name: string, value: string | undefined) {
    if (value === undefined || value === "" || value === "0" || value === "false") {
        return false;
    }
    if (value === "1" || value === "true") return true;
    throw new Error(`${name} must be one of 0, 1, false, or true`);
}

export function indexerGatewayEnabledFromEnvironment(value: string | undefined) {
    return booleanFlag("ONCHAIN_INDEXER_RPC_GATEWAY_ENABLED", value);
}

function exactKeys(value: object, expected: readonly string[]) {
    const actual = Object.keys(value).sort();
    return (
        actual.length === expected.length &&
        actual.every((key, index) => key === expected[index])
    );
}

function hasExactJsonContentType(response: Response) {
    return (
        response.headers
            .get("content-type")
            ?.split(";", 1)[0]
            ?.trim()
            .toLowerCase() === "application/json"
    );
}

function responseMatchesUrl(response: Response, expected: URL | string) {
    try {
        return new URL(response.url).toString() === new URL(expected).toString();
    } catch {
        return false;
    }
}

function parseGatewayRpcUrl(value: string) {
    let parsed: URL;
    try {
        parsed = new URL(value);
    } catch {
        throw new Error("ONCHAIN_INDEXER_RPC_URL must be an absolute URL");
    }
    if (
        !["http:", "https:"].includes(parsed.protocol) ||
        !parsed.hostname ||
        parsed.username ||
        parsed.password ||
        parsed.search ||
        parsed.hash ||
        parsed.pathname !== INDEXER_GATEWAY_RPC_PATH
    ) {
        throw new Error(
            `ONCHAIN_INDEXER_RPC_URL must be an HTTP(S) URL ending exactly in ${INDEXER_GATEWAY_RPC_PATH}`
        );
    }
    return parsed;
}

async function boundedJsonResponse(response: Response) {
    if (
        response.status !== 200 ||
        !hasExactJsonContentType(response)
    ) {
        throw new IndexerGatewayLeaseError();
    }
    const bytes = await boundedResponseBytes(response);
    let parsed: unknown;
    try {
        parsed = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
    } catch {
        throw new IndexerGatewayLeaseError();
    }
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        throw new IndexerGatewayLeaseError();
    }
    return parsed as Record<string, unknown>;
}

async function boundedResponseBytes(response: Response) {
    const declaredLength = response.headers.get("content-length");
    if (
        declaredLength !== null &&
        (!/^\d+$/.test(declaredLength) ||
            Number(declaredLength) > MAXIMUM_LEASE_CONTRACT_BYTES)
    ) {
        throw new IndexerGatewayLeaseError();
    }
    const reader = response.body?.getReader();
    if (!reader) throw new IndexerGatewayLeaseError();
    const chunks: Uint8Array[] = [];
    let byteLength = 0;
    try {
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            byteLength += value.byteLength;
            if (byteLength > MAXIMUM_LEASE_CONTRACT_BYTES) {
                await reader.cancel();
                throw new IndexerGatewayLeaseError();
            }
            chunks.push(value);
        }
    } catch (error) {
        if (error instanceof IndexerGatewayLeaseError) throw error;
        throw new IndexerGatewayLeaseError();
    }
    const bytes = new Uint8Array(byteLength);
    let offset = 0;
    for (const chunk of chunks) {
        bytes.set(chunk, offset);
        offset += chunk.byteLength;
    }
    return bytes;
}

async function gatewayContractRequest(input: {
    fetchFunction: FetchFunction;
    url: URL;
    authorization: string;
    body: object;
    leaseHeaders?: Readonly<Record<string, string>>;
}) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), GATEWAY_REQUEST_TIMEOUT_MS);
    try {
        const response = await input.fetchFunction(input.url, {
            method: "POST",
            headers: {
                Accept: "application/json",
                Authorization: input.authorization,
                "Cache-Control": "no-store",
                "Content-Type": "application/json",
                ...input.leaseHeaders,
            },
            body: JSON.stringify(input.body),
            cache: "no-store",
            redirect: "error",
            signal: controller.signal,
        });
        if (!responseMatchesUrl(response, input.url)) {
            throw new IndexerGatewayLeaseError();
        }
        return await boundedJsonResponse(response);
    } catch (error) {
        if (error instanceof IndexerGatewayLeaseError) throw error;
        throw new IndexerGatewayLeaseError();
    } finally {
        clearTimeout(timeout);
    }
}

function containsLeaseTransportFailure(error: unknown) {
    const seen = new Set<unknown>();
    let current = error;
    for (let depth = 0; depth < 16 && current && !seen.has(current); depth += 1) {
        seen.add(current);
        if (current instanceof IndexerGatewayLeaseError) return true;
        if (typeof current !== "object") return false;
        const named = current as { name?: unknown; cause?: unknown };
        if (
            named.name === "HttpRequestError" ||
            named.name === "TimeoutError" ||
            named.name === "AbortError"
        ) {
            return true;
        }
        current = named.cause;
    }
    return false;
}

function containsRangeReductionFailure(error: unknown) {
    const seen = new Set<unknown>();
    let current = error;
    for (let depth = 0; depth < 16 && current && !seen.has(current); depth += 1) {
        seen.add(current);
        if (current instanceof IndexerGatewayRangeReductionRequiredError) {
            return true;
        }
        if (typeof current !== "object") return false;
        current = (current as { cause?: unknown }).cause;
    }
    return false;
}

function containsRpcAccountingFailure(error: unknown) {
    const seen = new Set<unknown>();
    let current = error;
    for (let depth = 0; depth < 16 && current && !seen.has(current); depth += 1) {
        seen.add(current);
        if (
            current instanceof IndexerGatewayRpcMethodRejectedError
        ) {
            return true;
        }
        if (typeof current !== "object") return false;
        current = (current as { cause?: unknown }).cause;
    }
    return false;
}

async function isExactRangeReductionResponse(response: Response) {
    if (
        response.status !== 413 ||
        !hasExactJsonContentType(response)
    ) {
        return false;
    }
    try {
        const body = await boundedResponseBytes(response);
        const value = JSON.parse(
            new TextDecoder("utf-8", { fatal: true }).decode(body)
        ) as unknown;
        return Boolean(
            value &&
                typeof value === "object" &&
                !Array.isArray(value) &&
                exactKeys(value, ["formatVersion", "kind"]) &&
                (value as { kind?: unknown }).kind ===
                    "cybergold-rpc-indexer-range-reduction-required" &&
                (value as { formatVersion?: unknown }).formatVersion ===
                    INDEXER_GATEWAY_CONTRACT_VERSION
        );
    } catch {
        return false;
    }
}

export class PrivateIndexerGatewayLease {
    readonly reconciliationId: string;
    readonly finalizedAnchor: FinalizedRunAnchor;
    readonly configRevision: string;
    readonly expiresInSeconds: number;
    readonly expiresAtMs: number;

    #authorization: string;
    #fetchFunction: FetchFunction;
    #leaseToken: string;
    #now: () => number;
    #rpcUrl: string;
    #releaseUrl: URL;
    #released = false;
    #activeRequests = 0;
    #requestWaiters: Array<() => void> = [];

    constructor(input: {
        rpcUrl: URL;
        authorization: string;
        fetchFunction: FetchFunction;
        now: () => number;
        leaseToken: string;
        reconciliationId: string;
        finalizedAnchor: FinalizedRunAnchor;
        expiresInSeconds: number;
        configRevision: string;
    }) {
        const issuedAtMs = input.now();
        const expiresAtMs =
            issuedAtMs + input.expiresInSeconds * 1_000;
        if (
            !LEASE_TOKEN_PATTERN.test(input.leaseToken) ||
            !RECONCILIATION_ID_PATTERN.test(input.reconciliationId) ||
            !Number.isSafeInteger(input.expiresInSeconds) ||
            input.expiresInSeconds < 1 ||
            !Number.isSafeInteger(issuedAtMs) ||
            !Number.isSafeInteger(expiresAtMs) ||
            expiresAtMs <= issuedAtMs ||
            !CONFIG_REVISION_PATTERN.test(input.configRevision)
        ) {
            throw new IndexerGatewayLeaseError();
        }
        this.reconciliationId = input.reconciliationId;
        this.finalizedAnchor = Object.freeze({ ...input.finalizedAnchor });
        this.configRevision = input.configRevision;
        this.expiresInSeconds = input.expiresInSeconds;
        this.expiresAtMs = expiresAtMs;
        this.#authorization = input.authorization;
        this.#fetchFunction = input.fetchFunction;
        this.#leaseToken = input.leaseToken;
        this.#now = input.now;
        this.#rpcUrl = input.rpcUrl.toString();
        this.#releaseUrl = new URL(INDEXER_GATEWAY_LEASE_RELEASE_PATH, input.rpcUrl);
    }

    async #acquireRequestSlot() {
        if (this.#activeRequests >= GATEWAY_RPC_CONCURRENCY) {
            await new Promise<void>((resolve) => this.#requestWaiters.push(resolve));
            return;
        }
        this.#activeRequests += 1;
    }

    #releaseRequestSlot() {
        const waiter = this.#requestWaiters.shift();
        if (waiter) {
            waiter();
            return;
        }
        this.#activeRequests -= 1;
    }

    #leaseHeaders() {
        return {
            Authorization: this.#authorization,
            [INDEXER_GATEWAY_LEASE_TOKEN_HEADER]: this.#leaseToken,
            [INDEXER_GATEWAY_RECONCILIATION_HEADER]: this.reconciliationId,
        };
    }

    #leaseIsCurrent() {
        if (this.#released || this.#now() >= this.expiresAtMs) {
            throw new IndexerGatewayLeaseError();
        }
    }

    createRpcTransport(
        requestCounter: IndexerRpcRequestCounter,
        beforeRequest?: () => Promise<void>
    ) {
        const transport = http(this.#rpcUrl, {
            batch: false,
            retryCount: 0,
            timeout: GATEWAY_REQUEST_TIMEOUT_MS,
            fetchOptions: { headers: this.#leaseHeaders() },
            fetchFn: async (url, init) => {
                const requestUrl =
                    typeof url === "string" || url instanceof URL
                        ? new URL(url)
                        : new URL(url.url);
                if (requestUrl.toString() !== this.#rpcUrl) {
                    throw new IndexerGatewayLeaseError();
                }
                this.#leaseIsCurrent();
                if (beforeRequest) {
                    await beforeRequest();
                }
                this.#leaseIsCurrent();
                await this.#acquireRequestSlot();
                try {
                    this.#leaseIsCurrent();
                    return await this.#fetchFunction(url, {
                        ...init,
                        redirect: "error",
                    });
                } catch {
                    throw new IndexerGatewayLeaseError();
                } finally {
                    this.#releaseRequestSlot();
                }
            },
            onFetchResponse: async (response) => {
                if (!responseMatchesUrl(response, this.#rpcUrl)) {
                    throw new IndexerGatewayLeaseError();
                }
                if (response.ok) {
                    if (!hasExactJsonContentType(response)) {
                        throw new IndexerGatewayLeaseError();
                    }
                    return;
                }
                if (await isExactRangeReductionResponse(response)) {
                    throw new IndexerGatewayRangeReductionRequiredError();
                }
                throw new IndexerGatewayLeaseError();
            },
        });
        return (transportConfig: Parameters<typeof transport>[0]) => {
            const configured = transport(transportConfig);
            return {
                ...configured,
                request: (async (...args: Parameters<typeof configured.request>) => {
                    requestCounter.recordGatewayRpcAttempt(args[0].method);
                    try {
                        return await configured.request(...args);
                    } catch (error) {
                        requestCounter.recordGatewayRpcFailure();
                        throw error;
                    }
                }) as typeof configured.request,
            };
        };
    }

    isRestartRequiredError(error: unknown) {
        return (
            !containsRangeReductionFailure(error) &&
            containsLeaseTransportFailure(error)
        );
    }

    isRangeReductionRequiredError(error: unknown) {
        return containsRangeReductionFailure(error);
    }

    isRpcAccountingFailure(error: unknown) {
        return containsRpcAccountingFailure(error);
    }

    async release() {
        this.#leaseIsCurrent();
        if (this.#activeRequests !== 0 || this.#requestWaiters.length !== 0) {
            throw new IndexerGatewayLeaseError();
        }
        const response = await gatewayContractRequest({
            fetchFunction: this.#fetchFunction,
            url: this.#releaseUrl,
            authorization: this.#authorization,
            leaseHeaders: {
                [INDEXER_GATEWAY_LEASE_TOKEN_HEADER]: this.#leaseToken,
                [INDEXER_GATEWAY_RECONCILIATION_HEADER]: this.reconciliationId,
            },
            body: {
                kind: "cybergold-rpc-indexer-lease-release-request",
                formatVersion: INDEXER_GATEWAY_CONTRACT_VERSION,
                reconciliationId: this.reconciliationId,
            },
        });
        if (
            !exactKeys(response, [
                "formatVersion",
                "kind",
                "reconciliationId",
                "released",
            ]) ||
            response.kind !== "cybergold-rpc-indexer-lease-release" ||
            response.formatVersion !== INDEXER_GATEWAY_CONTRACT_VERSION ||
            response.reconciliationId !== this.reconciliationId ||
            response.released !== true
        ) {
            throw new IndexerGatewayLeaseError();
        }
        this.#released = true;
    }
}

export class PrivateIndexerGatewayClient {
    #authorization: string;
    #fetchFunction: FetchFunction;
    #now: () => number;
    #rpcUrl: URL;
    #acquireUrl: URL;

    constructor(rpcUrl: URL, clientToken: string, dependencies?: GatewayDependencies) {
        if (!LEASE_TOKEN_PATTERN.test(clientToken)) {
            throw new Error(
                "ONCHAIN_INDEXER_RPC_GATEWAY_TOKEN must be a 43-to-128-character URL-safe token"
            );
        }
        this.#authorization = `Bearer ${clientToken}`;
        this.#fetchFunction = dependencies?.fetch ?? fetch;
        this.#now = dependencies?.now ?? Date.now;
        this.#rpcUrl = new URL(rpcUrl);
        this.#acquireUrl = new URL(INDEXER_GATEWAY_LEASE_ACQUIRE_PATH, rpcUrl);
    }

    async acquire(expectation: IndexerGatewayLeaseExpectation) {
        const reconciliationId = expectation.reconciliationId;
        if (
            !RECONCILIATION_ID_PATTERN.test(reconciliationId) ||
            !CONFIG_REVISION_PATTERN.test(expectation.expectedRuntimeRevision) ||
            !Number.isSafeInteger(Number(expectation.expectedFinalizedAnchor.blockNumber)) ||
            expectation.expectedFinalizedAnchor.blockNumber < 0n ||
            !HASH_PATTERN.test(expectation.expectedFinalizedAnchor.blockHash)
        ) {
            throw new IndexerGatewayLeaseError();
        }
        const response = await gatewayContractRequest({
            fetchFunction: this.#fetchFunction,
            url: this.#acquireUrl,
            authorization: this.#authorization,
            body: {
                kind: "cybergold-rpc-indexer-lease-acquire-request",
                formatVersion: INDEXER_GATEWAY_LEASE_ACQUIRE_CONTRACT_VERSION,
                reconciliationId,
                expectedRuntimeRevision: expectation.expectedRuntimeRevision,
                expectedFinalizedAnchor: {
                    number: Number(expectation.expectedFinalizedAnchor.blockNumber),
                    hash: expectation.expectedFinalizedAnchor.blockHash,
                },
            },
        });
        if (
            !exactKeys(response, [
                "configRevision",
                "expiresInSeconds",
                "finalizedAnchor",
                "formatVersion",
                "kind",
                "leaseToken",
                "reconciliationId",
            ]) ||
            response.kind !== "cybergold-rpc-indexer-lease" ||
            response.formatVersion !== INDEXER_GATEWAY_CONTRACT_VERSION ||
            response.reconciliationId !== reconciliationId ||
            !response.finalizedAnchor ||
            typeof response.finalizedAnchor !== "object" ||
            Array.isArray(response.finalizedAnchor) ||
            !exactKeys(response.finalizedAnchor, ["hash", "number"])
        ) {
            throw new IndexerGatewayLeaseError();
        }
        const rawAnchor = response.finalizedAnchor as Record<string, unknown>;
        const blockNumber = rawAnchor.number;
        if (!Number.isSafeInteger(blockNumber) || (blockNumber as number) < 0) {
            throw new IndexerGatewayLeaseError();
        }
        let finalizedAnchor: FinalizedRunAnchor;
        try {
            finalizedAnchor = normalizeFinalizedRunAnchor({
                number: BigInt(blockNumber as number),
                hash: rawAnchor.hash as Hex,
            });
        } catch {
            throw new IndexerGatewayLeaseError();
        }
        if (
            response.configRevision !== expectation.expectedRuntimeRevision ||
            finalizedAnchor.blockNumber !==
                expectation.expectedFinalizedAnchor.blockNumber ||
            finalizedAnchor.blockHash.toLowerCase() !==
                expectation.expectedFinalizedAnchor.blockHash.toLowerCase()
        ) {
            throw new IndexerGatewayLeaseError();
        }
        return new PrivateIndexerGatewayLease({
            rpcUrl: this.#rpcUrl,
            authorization: this.#authorization,
            fetchFunction: this.#fetchFunction,
            now: this.#now,
            leaseToken: response.leaseToken as string,
            reconciliationId,
            finalizedAnchor,
            expiresInSeconds: response.expiresInSeconds as number,
            configRevision: response.configRevision as string,
        });
    }
}

export function privateIndexerGatewayFromEnvironment(
    environment: IndexerGatewayEnvironment,
    dependencies?: GatewayDependencies
) {
    const enabled = booleanFlag(
        "ONCHAIN_INDEXER_RPC_GATEWAY_ENABLED",
        environment.ONCHAIN_INDEXER_RPC_GATEWAY_ENABLED
    );
    const rpcUrl = environment.ONCHAIN_INDEXER_RPC_URL;
    const token = environment.ONCHAIN_INDEXER_RPC_GATEWAY_TOKEN;
    if (!enabled) {
        if (token !== undefined) {
            throw new Error(
                "Disabled indexer gateway configuration must not include a gateway token"
            );
        }
        return null;
    }
    if (!rpcUrl || !token) {
        throw new Error(
            "Enabled indexer gateway requires ONCHAIN_INDEXER_RPC_URL and ONCHAIN_INDEXER_RPC_GATEWAY_TOKEN"
        );
    }
    return new PrivateIndexerGatewayClient(
        parseGatewayRpcUrl(rpcUrl),
        token,
        dependencies
    );
}

export function assertPrivateIndexerGatewayRuntime(input: {
    enabled: boolean;
    chainId: bigint;
    archiveFreeFinalizedMode: boolean;
    addressScopedRawLogs: boolean;
}) {
    if (!input.enabled) return;
    if (
        input.chainId !== 1n ||
        !input.archiveFreeFinalizedMode ||
        !input.addressScopedRawLogs
    ) {
        throw new Error(
            "Private indexer gateway requires chain 1 archive-free finalized address-scoped mode"
        );
    }
}
