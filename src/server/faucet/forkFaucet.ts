import { serverEnv } from "../environment.ts";
import { execFile } from "node:child_process";
import { constants as fsConstants } from "node:fs";
import { access } from "node:fs/promises";
import { isIP } from "node:net";
import { homedir } from "node:os";
import path from "node:path";
import { promisify } from "node:util";

import { isAddress, type Address } from "viem";

const execFileAsync = promisify(execFile);

const DEFAULT_SCRIPT_PATHS = [
  path.resolve(
    process.cwd(),
    "../cybergold-ops/deploy/modules/fork/fund-wallet.sh"
  ),
];

const FAUCET_TIMEOUT_MS = 20_000;
const MAX_ADAPTER_RESPONSE_BYTES = 64 * 1024;
const MAX_UINT256 = (1n << 256n) - 1n;
const SERVICE_URL_PATTERN = /^http:\/\/127\.0\.0\.1:([1-9]\d{0,4})\/fund$/;
const SERVICE_TOKEN_PATTERN = /^[0-9a-f]{64}$/;
const REQUEST_ID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const DECIMAL_INTEGER_PATTERN = /^(0|[1-9]\d{0,77})$/;
const TOKEN_SYMBOL_PATTERN = /^[A-Za-z0-9]{1,16}$/;
const ADAPTER_ERROR_CODE_PATTERN = /^[A-Z][A-Z0-9_]{0,63}$/;
const ADAPTER_ERROR_CODES_BY_STATUS: Readonly<Record<number, readonly string[]>> = {
  400: [
    "INVALID_JSON",
    "INVALID_REQUEST",
    "INVALID_ADDRESS",
    "INVALID_REQUEST_ID",
    "INVALID_REQUESTER_IP",
  ],
  401: ["UNAUTHORIZED"],
  404: ["NOT_FOUND"],
  405: ["METHOD_NOT_ALLOWED"],
  408: ["REQUEST_TIMEOUT"],
  409: ["REQUEST_ID_CONFLICT", "REQUEST_IN_PROGRESS", "REQUEST_UNCERTAIN"],
  411: ["LENGTH_REQUIRED"],
  413: ["REQUEST_TOO_LARGE"],
  415: ["UNSUPPORTED_MEDIA_TYPE"],
  429: [
    "RATE_LIMITED",
    "ADDRESS_QUOTA_EXHAUSTED",
    "IP_QUOTA_EXHAUSTED",
    "GLOBAL_QUOTA_EXHAUSTED",
  ],
  500: ["INTERNAL_ERROR"],
  502: ["FUNDING_FAILED"],
  503: ["CHAIN_UNAVAILABLE"],
};

export type FaucetTokenFunding = {
  symbol: string;
  amount: string;
};

export type FaucetSuccessPayload = {
  status: "ok";
  address: Address;
  ethWei: string;
  tokens: FaucetTokenFunding[];
  dryRun: boolean;
};

type LegacyFaucetErrorPayload = {
  status: "error";
  address?: string;
  reason?: string;
};

export type FaucetErrorCode =
  | "DISABLED"
  | "INVALID_REQUEST"
  | "UNSUPPORTED_MEDIA_TYPE"
  | "REQUEST_TOO_LARGE"
  | "INTERNAL_ERROR"
  | "INVALID_ADDRESS"
  | "INVALID_REQUEST_ID"
  | "INVALID_REQUESTER_IP"
  | "CONFIGURATION_ERROR"
  | "REQUEST_REJECTED"
  | "AUTHENTICATION_FAILED"
  | "REQUEST_CONFLICT"
  | "REQUEST_IN_PROGRESS"
  | "REQUEST_UNCERTAIN"
  | "RATE_LIMITED"
  | "ADDRESS_QUOTA_EXHAUSTED"
  | "IP_QUOTA_EXHAUSTED"
  | "GLOBAL_QUOTA_EXHAUSTED"
  | "FUNDING_FAILED"
  | "CHAIN_UNAVAILABLE"
  | "TIMEOUT"
  | "BAD_GATEWAY"
  | "UNAVAILABLE"
  | "INVALID_RESPONSE"
  | "EXECUTION_FAILED";

export type ForkFaucetErrorCode = FaucetErrorCode;

export type FaucetRequestIdDisposition = "retain" | "replace";

export type FaucetAdapterDiagnostics = {
  stage: "faucet-adapter";
  elapsedMs: number;
  failureType: "http-error" | "invalid-response" | "backend-deadline" | "transport-error";
  httpStatus?: number;
  upstreamErrorCode?: string;
};

type ForkFaucetErrorDefinition = {
  message: string;
  status: number;
};

const ERROR_DEFINITIONS: Record<ForkFaucetErrorCode, ForkFaucetErrorDefinition> = {
  DISABLED: { message: "Fork faucet is disabled.", status: 403 },
  INVALID_REQUEST: { message: "Invalid request body.", status: 400 },
  UNSUPPORTED_MEDIA_TYPE: { message: "Content-Type must be application/json.", status: 415 },
  REQUEST_TOO_LARGE: { message: "Faucet request body is too large.", status: 413 },
  INTERNAL_ERROR: { message: "Fork faucet is temporarily unavailable.", status: 500 },
  INVALID_ADDRESS: { message: "Invalid wallet address.", status: 400 },
  INVALID_REQUEST_ID: { message: "Invalid faucet request ID.", status: 400 },
  INVALID_REQUESTER_IP: { message: "Requester IP is unavailable.", status: 400 },
  CONFIGURATION_ERROR: {
    message: "Fork faucet is temporarily unavailable.",
    status: 503,
  },
  REQUEST_REJECTED: { message: "Fork faucet request was rejected.", status: 400 },
  AUTHENTICATION_FAILED: {
    message: "Fork faucet is temporarily unavailable.",
    status: 502,
  },
  REQUEST_CONFLICT: {
    message: "Fork faucet request conflicts with an existing request.",
    status: 409,
  },
  REQUEST_IN_PROGRESS: { message: "Fork faucet request is still being processed.", status: 409 },
  REQUEST_UNCERTAIN: { message: "Fork faucet funding could not be confirmed.", status: 409 },
  RATE_LIMITED: { message: "Fork faucet rate limit exceeded.", status: 429 },
  ADDRESS_QUOTA_EXHAUSTED: { message: "Test funds quota for this wallet is exhausted.", status: 429 },
  IP_QUOTA_EXHAUSTED: { message: "Test funds quota for this connection is exhausted.", status: 429 },
  GLOBAL_QUOTA_EXHAUSTED: { message: "Sandbox test funds quota is exhausted.", status: 429 },
  FUNDING_FAILED: { message: "Fork faucet funding failed.", status: 502 },
  CHAIN_UNAVAILABLE: { message: "Sandbox chain is temporarily unavailable.", status: 503 },
  TIMEOUT: { message: "Fork faucet request timed out.", status: 504 },
  BAD_GATEWAY: { message: "Fork faucet is temporarily unavailable.", status: 502 },
  UNAVAILABLE: { message: "Fork faucet is temporarily unavailable.", status: 503 },
  INVALID_RESPONSE: {
    message: "Fork faucet is temporarily unavailable.",
    status: 502,
  },
  EXECUTION_FAILED: {
    message: "Fork faucet execution failed.",
    status: 500,
  },
};

export class ForkFaucetError extends Error {
  readonly code: ForkFaucetErrorCode;
  readonly status: number;
  readonly retryAfterSeconds?: number;
  readonly requestIdDisposition: FaucetRequestIdDisposition;
  diagnostics?: FaucetAdapterDiagnostics;

  constructor(
    code: ForkFaucetErrorCode,
    retryAfterSeconds?: number,
    requestIdDisposition: FaucetRequestIdDisposition = "retain"
  ) {
    const definition = ERROR_DEFINITIONS[code];
    super(definition.message);
    this.name = "ForkFaucetError";
    this.code = code;
    this.status = definition.status;
    this.retryAfterSeconds = retryAfterSeconds;
    this.requestIdDisposition = requestIdDisposition;
  }
}

export type ForkFaucetRequestContext = {
  requestId?: string;
  requesterIp?: string;
};

type ForkFaucetRuntime = {
  fetchImpl?: typeof fetch;
  adapterTimeoutMs?: number;
};

export function isForkFaucetEnabled() {
  return serverEnv.FORK_FAUCET_ENABLED === "1";
}

export function isForkFaucetAdapterMode() {
  return (
    serverEnv.FORK_FAUCET_SERVICE_URL !== undefined ||
    serverEnv.FORK_FAUCET_SERVICE_TOKEN !== undefined
  );
}

export function isValidFaucetRequestId(value: string) {
  return REQUEST_ID_PATTERN.test(value);
}

export function normalizeRequesterIp(value: string) {
  const version = isIP(value);
  if (version === 4) {
    return value;
  }
  if (version !== 6) {
    return undefined;
  }

  try {
    const hostname = new URL(`http://[${value}]/`).hostname;
    return hostname.slice(1, -1).toLowerCase();
  } catch {
    return undefined;
  }
}

async function fileExists(filePath: string) {
  try {
    await access(filePath, fsConstants.F_OK);
    return true;
  } catch {
    return false;
  }
}

async function resolveFaucetScriptPath() {
  const configuredPath = serverEnv.FORK_FAUCET_SCRIPT_PATH;

  if (configuredPath) {
    if (await fileExists(configuredPath)) {
      return configuredPath;
    }

    throw new ForkFaucetError("CONFIGURATION_ERROR");
  }

  for (const candidate of DEFAULT_SCRIPT_PATHS) {
    if (await fileExists(candidate)) {
      return candidate;
    }
  }

  throw new ForkFaucetError("CONFIGURATION_ERROR");
}

function buildFaucetEnv() {
  const home = serverEnv.FORK_FAUCET_HOME ?? process.env.HOME ?? homedir();
  const foundryBinDir = serverEnv.FOUNDRY_BIN_DIR ?? path.join(home, ".foundry", "bin");
  const basePath =
    process.env.PATH ?? "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin";

  return {
    ...process.env,
    HOME: home,
    PATH: `${foundryBinDir}:${basePath}`,
  };
}

function parseJson(raw: string): unknown {
  if (!raw) {
    return null;
  }

  try {
    return JSON.parse(raw) as unknown;
  } catch {
    return null;
  }
}

function isExactObject(
  value: unknown,
  expectedKeys: readonly string[]
): value is Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }

  const keys = Object.keys(value as Record<string, unknown>).sort();
  return (
    keys.length === expectedKeys.length &&
    keys.every((key, index) => key === [...expectedKeys].sort()[index])
  );
}

function isUint256Decimal(value: unknown): value is string {
  if (typeof value !== "string" || !DECIMAL_INTEGER_PATTERN.test(value)) {
    return false;
  }

  try {
    return BigInt(value) <= MAX_UINT256;
  } catch {
    return false;
  }
}

function parseSuccessPayload(
  value: unknown,
  expectedAddress: string,
  requireLiveExecution: boolean
): FaucetSuccessPayload | null {
  if (
    !isExactObject(value, ["address", "dryRun", "ethWei", "status", "tokens"]) ||
    value.status !== "ok" ||
    typeof value.address !== "string" ||
    !isAddress(value.address) ||
    value.address.toLowerCase() !== expectedAddress.toLowerCase() ||
    !isUint256Decimal(value.ethWei) ||
    !Array.isArray(value.tokens) ||
    value.tokens.length > 16 ||
    typeof value.dryRun !== "boolean" ||
    (requireLiveExecution && value.dryRun !== false)
  ) {
    return null;
  }

  const tokens: FaucetTokenFunding[] = [];
  const seenSymbols = new Set<string>();
  for (const token of value.tokens) {
    if (
      !isExactObject(token, ["amount", "symbol"]) ||
      typeof token.symbol !== "string" ||
      !TOKEN_SYMBOL_PATTERN.test(token.symbol) ||
      !isUint256Decimal(token.amount)
    ) {
      return null;
    }

    const normalizedSymbol = token.symbol.toUpperCase();
    if (seenSymbols.has(normalizedSymbol)) {
      return null;
    }
    seenSymbols.add(normalizedSymbol);
    tokens.push({ symbol: token.symbol, amount: token.amount });
  }

  return {
    status: "ok",
    address: value.address,
    ethWei: value.ethWei,
    tokens,
    dryRun: value.dryRun,
  };
}

function resolveAdapterConfiguration() {
  const serviceUrl = serverEnv.FORK_FAUCET_SERVICE_URL;
  const serviceToken = serverEnv.FORK_FAUCET_SERVICE_TOKEN;
  const match = serviceUrl?.match(SERVICE_URL_PATTERN);
  const port = match ? Number(match[1]) : Number.NaN;

  if (
    !serviceUrl ||
    !match ||
    !Number.isInteger(port) ||
    port < 1 ||
    port > 65_535 ||
    !serviceToken ||
    !SERVICE_TOKEN_PATTERN.test(serviceToken)
  ) {
    throw new ForkFaucetError("CONFIGURATION_ERROR");
  }

  return { serviceUrl, serviceToken };
}

function parseRetryAfter(value: string | null) {
  if (!value || !/^\d{1,4}$/.test(value)) {
    return undefined;
  }

  const seconds = Number(value);
  return seconds >= 1 && seconds <= 3_600 ? seconds : undefined;
}

function errorFromAdapterStatus(response: Response, adapterCode: string) {
  const requestIdDisposition: FaucetRequestIdDisposition = [
    "FUNDING_FAILED",
    "REQUEST_ID_CONFLICT",
    "REQUEST_UNCERTAIN",
  ].includes(adapterCode)
    ? "replace"
    : "retain";
  switch (response.status) {
    case 400:
      return new ForkFaucetError("REQUEST_REJECTED", undefined, requestIdDisposition);
    case 401:
      return new ForkFaucetError("AUTHENTICATION_FAILED", undefined, requestIdDisposition);
    case 408:
      return new ForkFaucetError("TIMEOUT", undefined, requestIdDisposition);
    case 409:
      return new ForkFaucetError(
        adapterCode === "REQUEST_ID_CONFLICT" ? "REQUEST_CONFLICT" : adapterCode as "REQUEST_IN_PROGRESS" | "REQUEST_UNCERTAIN",
        undefined,
        requestIdDisposition
      );
    case 429:
      return new ForkFaucetError(
        adapterCode as "RATE_LIMITED" | "ADDRESS_QUOTA_EXHAUSTED" | "IP_QUOTA_EXHAUSTED" | "GLOBAL_QUOTA_EXHAUSTED",
        parseRetryAfter(response.headers.get("retry-after")),
        requestIdDisposition
      );
    case 502:
      return new ForkFaucetError("FUNDING_FAILED", undefined, requestIdDisposition);
    case 503:
      return new ForkFaucetError("CHAIN_UNAVAILABLE", undefined, requestIdDisposition);
    default:
      return new ForkFaucetError("BAD_GATEWAY", undefined, requestIdDisposition);
  }
}

function hasJsonResponseContentType(response: Response) {
  const contentType = response.headers.get("content-type")?.split(";", 1)[0].trim();
  return contentType?.toLowerCase() === "application/json";
}

async function readBoundedResponseBody(response: Response) {
  const declaredLength = response.headers.get("content-length");
  if (declaredLength !== null) {
    if (!/^\d+$/.test(declaredLength) || Number(declaredLength) > MAX_ADAPTER_RESPONSE_BYTES) {
      throw new ForkFaucetError("INVALID_RESPONSE");
    }
  }

  if (!response.body) {
    throw new ForkFaucetError("INVALID_RESPONSE");
  }

  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let receivedBytes = 0;

  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }

    receivedBytes += value.byteLength;
    if (receivedBytes > MAX_ADAPTER_RESPONSE_BYTES) {
      await reader.cancel();
      throw new ForkFaucetError("INVALID_RESPONSE");
    }
    chunks.push(value);
  }

  const body = new Uint8Array(receivedBytes);
  let offset = 0;
  for (const chunk of chunks) {
    body.set(chunk, offset);
    offset += chunk.byteLength;
  }

  try {
    return new TextDecoder("utf-8", { fatal: true }).decode(body);
  } catch {
    throw new ForkFaucetError("INVALID_RESPONSE");
  }
}

async function validateAdapterErrorResponse(response: Response) {
  if (!hasJsonResponseContentType(response)) {
    throw new ForkFaucetError("INVALID_RESPONSE");
  }

  const payload = parseJson(await readBoundedResponseBody(response));
  if (!isExactObject(payload, ["error"])) {
    throw new ForkFaucetError("INVALID_RESPONSE");
  }

  const adapterError = payload.error;
  if (
    !isExactObject(adapterError, ["code", "message"]) ||
    typeof adapterError.code !== "string" ||
    !ADAPTER_ERROR_CODE_PATTERN.test(adapterError.code) ||
    typeof adapterError.message !== "string" ||
    adapterError.message.length < 1 ||
    adapterError.message.length > 512
  ) {
    throw new ForkFaucetError("INVALID_RESPONSE");
  }

  const allowedCodes = ADAPTER_ERROR_CODES_BY_STATUS[response.status];
  if (!allowedCodes?.includes(adapterError.code)) {
    throw new ForkFaucetError("INVALID_RESPONSE");
  }

  return adapterError.code;
}

async function fundThroughAdapter(
  address: string,
  context: ForkFaucetRequestContext,
  runtime: ForkFaucetRuntime
) {
  const { serviceUrl, serviceToken } = resolveAdapterConfiguration();
  if (!context.requestId || !isValidFaucetRequestId(context.requestId)) {
    throw new ForkFaucetError("INVALID_REQUEST_ID");
  }
  if (
    !context.requesterIp ||
    normalizeRequesterIp(context.requesterIp) !== context.requesterIp
  ) {
    throw new ForkFaucetError("INVALID_REQUESTER_IP");
  }

  const timeoutMs = Math.max(
    1,
    Math.min(runtime.adapterTimeoutMs ?? FAUCET_TIMEOUT_MS, FAUCET_TIMEOUT_MS)
  );
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  const started = performance.now();
  let httpStatus: number | undefined;
  let upstreamErrorCode: string | undefined;

  try {
    const response = await (runtime.fetchImpl ?? fetch)(serviceUrl, {
      method: "POST",
      headers: {
        Accept: "application/json",
        Authorization: `Bearer ${serviceToken}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        address,
        requestId: context.requestId,
        requesterIp: context.requesterIp,
      }),
      cache: "no-store",
      credentials: "omit",
      redirect: "error",
      signal: controller.signal,
    });
    httpStatus = response.status;

    if (response.status !== 200) {
      const adapterCode = await validateAdapterErrorResponse(response);
      upstreamErrorCode = adapterCode;
      throw errorFromAdapterStatus(response, adapterCode);
    }

    if (!hasJsonResponseContentType(response)) {
      throw new ForkFaucetError("INVALID_RESPONSE");
    }

    const rawBody = await readBoundedResponseBody(response);
    const payload = parseSuccessPayload(parseJson(rawBody), address, true);
    if (!payload) {
      throw new ForkFaucetError("INVALID_RESPONSE");
    }

    return payload;
  } catch (error) {
    const failure = error instanceof ForkFaucetError
      ? error
      : new ForkFaucetError(controller.signal.aborted ? "TIMEOUT" : "BAD_GATEWAY");
    failure.diagnostics = {
      stage: "faucet-adapter",
      elapsedMs: Math.round(performance.now() - started),
      failureType: upstreamErrorCode !== undefined ? "http-error"
        : failure.code === "INVALID_RESPONSE" ? "invalid-response"
        : controller.signal.aborted ? "backend-deadline" : "transport-error",
      ...(httpStatus !== undefined ? { httpStatus } : {}),
      ...(upstreamErrorCode !== undefined ? { upstreamErrorCode } : {}),
    };
    throw failure;
  } finally {
    clearTimeout(timeout);
  }
}

function classifyLegacyFailure(stdout: string | undefined) {
  const payload = parseJson(stdout ?? "");
  if (
    isExactObject(payload, ["address", "reason", "status"]) ||
    isExactObject(payload, ["reason", "status"])
  ) {
    const legacyError = payload as LegacyFaucetErrorPayload;
    if (legacyError.status === "error" && typeof legacyError.reason === "string") {
      const reason = legacyError.reason.toLowerCase();
      if (reason.includes("cooldown") || reason.includes("limit") || reason.includes("max calls")) {
        return new ForkFaucetError("RATE_LIMITED");
      }
      if (reason.includes("not allowed")) {
        return new ForkFaucetError("REQUEST_REJECTED");
      }
    }
  }

  return new ForkFaucetError("EXECUTION_FAILED");
}

async function fundThroughLegacyScript(address: string) {
  if (process.env.NODE_ENV === "production") {
    throw new ForkFaucetError("CONFIGURATION_ERROR");
  }

  const scriptPath = await resolveFaucetScriptPath();

  try {
    const { stdout } = await execFileAsync(scriptPath, [address, "--json"], {
      env: buildFaucetEnv(),
      maxBuffer: 1024 * 1024,
      timeout: FAUCET_TIMEOUT_MS,
    });

    const payload = parseSuccessPayload(parseJson(stdout.trim()), address, false);
    if (!payload) {
      throw new ForkFaucetError("INVALID_RESPONSE");
    }

    return payload;
  } catch (error) {
    if (error instanceof ForkFaucetError) {
      throw error;
    }

    const execError = error as Error & { killed?: boolean; stdout?: string };
    if (execError.killed) {
      throw new ForkFaucetError("TIMEOUT");
    }
    throw classifyLegacyFailure(execError.stdout);
  }
}

export async function fundForkWallet(
  address: string,
  context: ForkFaucetRequestContext = {},
  runtime: ForkFaucetRuntime = {}
): Promise<FaucetSuccessPayload> {
  if (!isForkFaucetEnabled()) {
    throw new ForkFaucetError("DISABLED");
  }

  if (!isAddress(address)) {
    throw new ForkFaucetError("INVALID_ADDRESS");
  }

  if (isForkFaucetAdapterMode()) {
    return fundThroughAdapter(address, context, runtime);
  }

  return fundThroughLegacyScript(address);
}
