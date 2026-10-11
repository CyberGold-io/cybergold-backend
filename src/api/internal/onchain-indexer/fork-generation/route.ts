import {
  getSandboxForkGenerationStatus,
  transitionSandboxForkGeneration,
} from "@/server/onchain-indexer/indexer";
import { readInternalForkGenerationRequest } from "@/server/onchain-indexer/internalForkGenerationContract";
import { authorizeIndexerWorker } from "@/server/onchain-indexer/workerAuth";
import { internalIndexerDiagnostic } from "@/server/onchain-indexer/internalIndexerDiagnostic";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
const HEADERS = { "Cache-Control": "no-store" };

function authorizationFailure(request: Request) {
  const decision = authorizeIndexerWorker(request.headers.get("authorization"));
  if (decision === "not-configured") {
    return Response.json({ error: "On-chain indexer worker is not configured" }, { status: 503, headers: HEADERS });
  }
  if (decision !== "authorized") {
    return Response.json({ error: "Unauthorized" }, { status: 401, headers: HEADERS });
  }
  return null;
}

export async function GET(request: Request) {
  const failure = authorizationFailure(request);
  if (failure) return failure;
  try {
    return Response.json({
      kind: "cybergold-sandbox-fork-generation-status",
      formatVersion: 1,
      current: await getSandboxForkGenerationStatus(),
    }, { headers: HEADERS });
  } catch (error) {
    console.error("Sandbox fork generation status failed", { diagnostic: internalIndexerDiagnostic(error) });
    return Response.json({ error: "Sandbox fork generation status failed" }, { status: 503, headers: HEADERS });
  }
}

export async function POST(request: Request) {
  const failure = authorizationFailure(request);
  if (failure) return failure;
  let parsed: Awaited<ReturnType<typeof readInternalForkGenerationRequest>>;
  try {
    parsed = await readInternalForkGenerationRequest(request);
  } catch {
    return Response.json({ error: "Invalid Sandbox fork generation request" }, { status: 400, headers: HEADERS });
  }
  try {
    const result = await transitionSandboxForkGeneration(parsed);
    if (result.status === "busy") {
      return Response.json({ status: "busy" }, { status: 409, headers: { ...HEADERS, "Retry-After": "1" } });
    }
    return Response.json({
      status: result.status,
      ...(result.status === "applied" ? {
        plan: {
          kind: result.plan.kind,
          invalidateFrom: result.plan.invalidateFrom.toString(),
          retainedThrough: result.plan.retainedThrough?.toString() ?? null,
        },
      } : {}),
    }, { headers: HEADERS });
  } catch (error) {
    console.error("Sandbox fork generation transition failed", { diagnostic: internalIndexerDiagnostic(error) });
    return Response.json({ error: "Sandbox fork generation transition failed" }, { status: 503, headers: HEADERS });
  }
}
