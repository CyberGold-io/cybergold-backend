import {
  getSafeExecutionStatuses,
  SafeEventApiLimitError,
} from "@/server/safe-events/indexer";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type SafeEventsRequest = {
  safeAddress?: string;
  safeTxHashes?: string[];
};

function jsonError(message: string, status = 400) {
  return Response.json({ error: message }, { status, headers: { "Cache-Control": "no-store" } });
}

async function readBoundedJson(request: Request, maximumBytes: number) {
  if (!request.body) throw new Error("empty body");
  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > maximumBytes) {
      await reader.cancel();
      throw new RangeError("request body is too large");
    }
    chunks.push(value);
  }
  const bytes = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return JSON.parse(new TextDecoder().decode(bytes)) as unknown;
}

export async function POST(request: Request) {
  let body: SafeEventsRequest;

  const contentLength = Number(request.headers.get("content-length") ?? "0");
  if (Number.isFinite(contentLength) && contentLength > 16_384) {
    return jsonError("Safe event request body is too large.", 413);
  }

  try {
    body = (await readBoundedJson(request, 16_384)) as SafeEventsRequest;
  } catch (error) {
    if (error instanceof RangeError) {
      return jsonError("Safe event request body is too large.", 413);
    }
    return jsonError("Invalid JSON payload.");
  }

  if (!body.safeAddress) {
    return jsonError("Missing safeAddress.");
  }
  if (!Array.isArray(body.safeTxHashes)) {
    return jsonError("Missing safeTxHashes.");
  }

  try {
    const results = await getSafeExecutionStatuses(body.safeAddress, body.safeTxHashes);
    return Response.json({ results }, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    if (error instanceof SafeEventApiLimitError) {
      return Response.json(
        { error: error.message },
        {
          status: 429,
          headers: {
            "Cache-Control": "no-store",
            "Retry-After": String(error.retryAfterSeconds),
          },
        }
      );
    }
    return Response.json(
      {
        error: error instanceof Error ? error.message : "Failed to index Safe execution events.",
      },
      { status: 500, headers: { "Cache-Control": "no-store" } }
    );
  }
}
