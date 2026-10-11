const READ_ONLY_RPC_METHODS = new Set([
  "eth_blockNumber",
  "eth_call",
  "eth_chainId",
  "eth_estimateGas",
  "eth_feeHistory",
  "eth_gasPrice",
  "eth_getBalance",
  "eth_getBlockByHash",
  "eth_getBlockByNumber",
  "eth_getBlockReceipts",
  "eth_getBlockTransactionCountByHash",
  "eth_getBlockTransactionCountByNumber",
  "eth_getCode",
  "eth_getLogs",
  "eth_getProof",
  "eth_getStorageAt",
  "eth_getTransactionByBlockHashAndIndex",
  "eth_getTransactionByBlockNumberAndIndex",
  "eth_getTransactionByHash",
  "eth_getTransactionCount",
  "eth_getTransactionReceipt",
  "eth_maxPriorityFeePerGas",
  "eth_syncing",
  "net_listening",
  "net_peerCount",
  "net_version",
  "web3_clientVersion",
]);

export const MAX_RPC_REQUEST_BYTES = 1024 * 1024;
export const MAX_RPC_BATCH_SIZE = 100;

type JsonRpcRecord = Record<string, unknown>;

export type RpcPayloadValidation =
  | { ok: true }
  | {
      ok: false;
      code: -32600 | -32601;
      message: "Invalid JSON-RPC request." | "JSON-RPC method is not allowed.";
    };

function isRecord(value: unknown): value is JsonRpcRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasOwn(record: JsonRpcRecord, key: string) {
  return Object.prototype.hasOwnProperty.call(record, key);
}

function isValidRequestId(id: unknown) {
  return (
    id === null ||
    typeof id === "string" ||
    (typeof id === "number" && Number.isFinite(id))
  );
}

function validateRequest(request: unknown): RpcPayloadValidation {
  if (!isRecord(request)) {
    return { ok: false, code: -32600, message: "Invalid JSON-RPC request." };
  }

  if (
    request.jsonrpc !== "2.0" ||
    typeof request.method !== "string" ||
    !hasOwn(request, "id") ||
    !isValidRequestId(request.id) ||
    (hasOwn(request, "params") &&
      !Array.isArray(request.params) &&
      !isRecord(request.params))
  ) {
    return { ok: false, code: -32600, message: "Invalid JSON-RPC request." };
  }

  if (!READ_ONLY_RPC_METHODS.has(request.method)) {
    return {
      ok: false,
      code: -32601,
      message: "JSON-RPC method is not allowed.",
    };
  }

  return { ok: true };
}

export function validateRpcPayload(payload: unknown): RpcPayloadValidation {
  if (Array.isArray(payload)) {
    if (payload.length === 0 || payload.length > MAX_RPC_BATCH_SIZE) {
      return { ok: false, code: -32600, message: "Invalid JSON-RPC request." };
    }

    for (const request of payload) {
      const validation = validateRequest(request);
      if (!validation.ok) {
        return validation;
      }
    }

    return { ok: true };
  }

  return validateRequest(payload);
}

function isValidResponseId(id: unknown) {
  return isValidRequestId(id);
}

function isValidRpcResponse(response: unknown) {
  if (
    !isRecord(response) ||
    response.jsonrpc !== "2.0" ||
    !hasOwn(response, "id") ||
    !isValidResponseId(response.id)
  ) {
    return false;
  }

  const hasResult = hasOwn(response, "result");
  const hasError = hasOwn(response, "error");
  if (hasResult === hasError) {
    return false;
  }

  if (!hasError) {
    return true;
  }

  const error = response.error;
  return (
    isRecord(error) &&
    typeof error.code === "number" &&
    Number.isFinite(error.code) &&
    typeof error.message === "string"
  );
}

export function isValidRpcResponsePayload(payload: unknown) {
  if (Array.isArray(payload)) {
    return payload.length > 0 && payload.every(isValidRpcResponse);
  }

  return isValidRpcResponse(payload);
}

export function parseRpcUpstreamUrl(value: string | undefined) {
  if (!value) {
    return null;
  }

  try {
    const url = new URL(value);
    if (url.protocol !== "http:" && url.protocol !== "https:") {
      return null;
    }
    return url;
  } catch {
    return null;
  }
}
