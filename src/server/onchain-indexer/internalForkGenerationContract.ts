import type { ForkGenerationAnchor } from "./forkGenerationTransition.ts";

const HASH = /^0x[0-9a-fA-F]{64}$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const DECIMAL = /^(?:0|[1-9][0-9]*)$/;

function exactKeys(value: object, expected: readonly string[]) {
  const actual = Object.keys(value).sort();
  const sortedExpected = [...expected].sort();
  return actual.length === expected.length &&
    actual.every((key, index) => key === sortedExpected[index]);
}

function anchor(value: unknown): ForkGenerationAnchor {
  if (!value || typeof value !== "object" || Array.isArray(value) ||
      !exactKeys(value, ["generation", "forkBlock", "forkBlockHash"])) {
    throw new Error("Sandbox fork anchor shape is invalid");
  }
  const row = value as Record<string, unknown>;
  if (typeof row.generation !== "string" || !UUID.test(row.generation) ||
      typeof row.forkBlock !== "string" || !DECIMAL.test(row.forkBlock) ||
      typeof row.forkBlockHash !== "string" || !HASH.test(row.forkBlockHash)) {
    throw new Error("Sandbox fork anchor identity is invalid");
  }
  return {
    generation: row.generation,
    forkBlock: BigInt(row.forkBlock),
    forkBlockHash: row.forkBlockHash.toLowerCase(),
  };
}

export function parseInternalForkGenerationRequest(body: unknown):
  | { action: "prepare"; current: ForkGenerationAnchor }
  | { action: "apply"; previous: ForkGenerationAnchor; current: ForkGenerationAnchor } {
  if (!body || typeof body !== "object" || Array.isArray(body)) {
    throw new Error("Sandbox fork request shape is invalid");
  }
  const row = body as Record<string, unknown>;
  if (row.kind !== "cybergold-sandbox-fork-generation" || row.formatVersion !== 1) {
    throw new Error("Sandbox fork request identity is invalid");
  }
  if (row.action === "prepare" &&
      exactKeys(row, ["kind", "formatVersion", "action", "current"])) {
    return { action: "prepare", current: anchor(row.current) };
  }
  if (row.action === "apply" &&
      exactKeys(row, ["kind", "formatVersion", "action", "previous", "current"])) {
    return { action: "apply", previous: anchor(row.previous), current: anchor(row.current) };
  }
  throw new Error("Sandbox fork request shape is invalid");
}

export async function readInternalForkGenerationRequest(request: Request) {
  if (!request.headers.get("content-type")?.toLowerCase().startsWith("application/json")) {
    throw new Error("Sandbox fork request content type is invalid");
  }
  if (!request.body) throw new Error("Sandbox fork request body is missing");
  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let bytes = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      bytes += value.byteLength;
      if (bytes > 1024) throw new Error("Sandbox fork request exceeds 1024 bytes");
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }
  const text = Buffer.concat(chunks, bytes).toString("utf8");
  return parseInternalForkGenerationRequest(JSON.parse(text));
}
