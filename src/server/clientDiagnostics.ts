import type { FastifyInstance } from "fastify";
import type { QuoteConstraint } from "../contracts/dto";

export type ClientDiagnostic = {
  operation?: "quote" | "swap" | "wallet";
  outcome?: "started" | "succeeded" | "failed" | "submitted" | "reverted" | "unconfirmed" | "requested";
  reason?: "wallet_rejected" | "rpc_error" | "contract_reverted" | "wrong_chain" | "unknown";
  /**
   * Numeric wallet or JSON-RPC code; no error message or provider text.
   * @TJS-type integer
   * @minimum -9007199254740991
   * @maximum 9007199254740991
   */
  errorCode?: number;
  /**
   * Four-byte EVM error selector only; no encoded arguments or calldata.
   * @pattern ^0x[0-9a-fA-F]{8}$
   */
  errorSelector?: string;
  direction?: "issue" | "redeem";
  route?: "basket" | "token";
  inputMode?: "exact-in" | "exact-out";
  walletStep?: "approval" | "signature" | "transaction";
  attemptId?: string;
  quoteId?: string;
  requestId?: string;
  correlationId?: string;
  workId?: string;
  side?: "buy" | "sell";
  strategy?: "core" | "market";
  stage?: "quote" | "balance" | "network" | "authorization" | "preparation" | "simulation" | "submission" | "confirmation";
  constraint?: QuoteConstraint;
  errorClassification?: "insufficient-protocol-supply" | "issuance-cap-exceeded" | "redemption-supply-exceeded" | "redemption-capacity-exceeded" | "rpc-rate-limit" | "rpc-timeout"
    | "rpc-unavailable" | "rpc-access-denied" | "quote-timeout" | "quote-no-route" | "quote-contract-reverted" | "quote-unavailable"
    | "quote-service-unavailable" | "quote-stream-interrupted" | "quote-invalid-input" | "quote-request-limit";
  tokenIn?: string;
  tokenOut?: string;
  amount?: string;
  inputMaximum?: string;
  outputMinimum?: string;
  blockNumber?: string;
  blockHash?: string;
  transactionHash?: string;
  durationMs?: number;
  chainId?: number;
  assetCount?: number;
};

/** Project untrusted diagnostics onto explicit fields. Never log the input object. */
export function projectClientDiagnostic(input: unknown): ClientDiagnostic {
  const source = input && typeof input === "object" ? input as Record<string, unknown> : {};
  const result: Record<string, unknown> = {};
  const enums = {
    operation: ["quote", "swap", "wallet"],
    outcome: ["started", "succeeded", "failed", "submitted", "reverted", "unconfirmed", "requested"],
    reason: ["wallet_rejected", "rpc_error", "contract_reverted", "wrong_chain", "unknown"],
    direction: ["issue", "redeem"], route: ["basket", "token"], inputMode: ["exact-in", "exact-out"],
    walletStep: ["approval", "signature", "transaction"],
    side: ["buy", "sell"], strategy: ["core", "market"],
    stage: ["quote", "balance", "network", "authorization", "preparation", "simulation", "submission", "confirmation"],
    errorClassification: ["insufficient-protocol-supply", "issuance-cap-exceeded", "redemption-supply-exceeded", "redemption-capacity-exceeded", "rpc-rate-limit", "rpc-timeout",
      "rpc-unavailable", "rpc-access-denied", "quote-timeout", "quote-no-route", "quote-contract-reverted", "quote-unavailable",
      "quote-service-unavailable", "quote-stream-interrupted", "quote-invalid-input", "quote-request-limit"],
  };
  for (const [key, values] of Object.entries(enums)) {
    if (typeof source[key] === "string" && values.includes(source[key])) result[key] = source[key];
  }
  for (const key of ["attemptId", "quoteId", "requestId", "correlationId", "workId"]) {
    if (typeof source[key] === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(source[key])) {
      result[key] = source[key];
    }
  }
  if (typeof source.transactionHash === "string" && /^0x[0-9a-f]{64}$/i.test(source.transactionHash)) {
    result.transactionHash = source.transactionHash;
  }
  for (const key of ["durationMs", "chainId", "assetCount"]) {
    if (typeof source[key] === "number" && Number.isSafeInteger(source[key]) && source[key] >= 0) result[key] = source[key];
  }
  if (typeof source.errorCode === "number" && Number.isSafeInteger(source.errorCode)) result.errorCode = source.errorCode;
  if (typeof source.errorSelector === "string" && /^0x[0-9a-fA-F]{8}$/.test(source.errorSelector)) {
    result.errorSelector = source.errorSelector.toLowerCase();
  }
  for (const key of ["tokenIn", "tokenOut"]) {
    if (typeof source[key] === "string" && /^0x[0-9a-fA-F]{40}$/.test(source[key])) result[key] = source[key];
  }
  for (const key of ["amount", "inputMaximum", "outputMinimum", "blockNumber"]) {
    if (typeof source[key] === "string" && /^[0-9]{1,78}$/.test(source[key]) && BigInt(source[key]) < 2n ** 256n) result[key] = source[key];
  }
  if (typeof source.blockHash === "string" && /^0x[0-9a-fA-F]{64}$/.test(source.blockHash)) result.blockHash = source.blockHash;
  const constraint = source.constraint;
  if (constraint && typeof constraint === "object") {
    const values = constraint as Record<string, unknown>;
    const projected: Record<string, string> = {};
    const kinds = {
      kind: ["issuance-cap", "redemption-supply", "redemption-capacity"],
      quantity: ["gross-cygld-mint", "gross-cygld-input", "core-output-minima"],
      limitKind: ["maximum-total-supply", "effective-supply-cap"],
    };
    for (const [key, allowed] of Object.entries(kinds)) {
      if (typeof values[key] === "string" && allowed.includes(values[key])) projected[key] = values[key];
    }
    for (const key of ["requestedRaw", "availableRaw", "currentSupplyRaw", "limitRaw"]) {
      if (typeof values[key] === "string" && /^[0-9]{1,78}$/.test(values[key]) && BigInt(values[key]) < 2n ** 256n) projected[key] = values[key];
    }
    if (Object.keys(projected).length) result.constraint = projected;
  }
  return result as ClientDiagnostic;
}

export const CLIENT_DIAGNOSTICS_PATH = "/api/diagnostics";

export async function registerClientDiagnostics(app: FastifyInstance) {
  // Use Fastify's standard JSON parser and default body limit for this new route.
  // Encapsulation leaves the older compatibility routes' raw parsers unchanged.
  await app.register(async diagnostics => {
    diagnostics.removeAllContentTypeParsers();
    diagnostics.addContentTypeParser("application/json", { parseAs: "string" },
      diagnostics.getDefaultJsonParser("error", "error"));
    diagnostics.setErrorHandler((error, _request, reply) => {
      const status = (error as { statusCode?: number }).statusCode ?? 500;
      reply.code(status).header("Cache-Control", "no-store").send({ error: "Diagnostic could not be read." });
    });
    diagnostics.post(CLIENT_DIAGNOSTICS_PATH, async (request, reply) => {
      const diagnostic = projectClientDiagnostic(request.body);
      if (diagnostic.operation && diagnostic.outcome) {
        try {
          app.log.info({ ...diagnostic, event: "client_diagnostic", source: "browser",
            component: "api", requestId: diagnostic.requestId ?? request.id,
            diagnosticRequestId: request.id, release: process.env.CYBERGOLD_BACKEND_COMMIT },
          "DApp diagnostic");
        } catch { /* Telemetry must not become a product dependency. */ }
      }
      return reply.code(202).header("Cache-Control", "no-store").send({ accepted: true });
    });
  });
}
