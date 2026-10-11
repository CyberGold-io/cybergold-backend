import { indexerRuns, observeIndexer, observeMetrics } from "@/server/metrics";
import { protocolMetrics } from "@/server/protocolMetrics";
import {
    getLastOnchainIndexerReconciliationReceipt,
    runOnchainIndexerWorkerOnce,
    type OnchainIndexerDiagnosticStage,
} from "@/server/onchain-indexer/indexer";
import { authorizeIndexerWorker } from "@/server/onchain-indexer/workerAuth";
import { internalIndexerDiagnostic } from "@/server/onchain-indexer/internalIndexerDiagnostic";
import {
    buildInternalReconcileResponse,
    parseInternalReconcileRequest,
} from "@/server/onchain-indexer/internalReconcileContract";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const NO_STORE = { "Cache-Control": "no-store" };

function reportIndexerError(context: string, error: unknown) {
    console.error(
        context,
        { diagnostic: internalIndexerDiagnostic(error) }
    );
}

function authorizationFailure(request: Request) {
    const authorization = authorizeIndexerWorker(request.headers.get("authorization"));
    if (authorization === "not-configured") {
        return Response.json(
            { error: "On-chain indexer worker is not configured" },
            { status: 503, headers: NO_STORE }
        );
    }
    if (authorization !== "authorized") {
        return Response.json(
            { error: "Unauthorized" },
            { status: 401, headers: NO_STORE }
        );
    }
    return null;
}

export async function GET(request: Request) {
    const failure = authorizationFailure(request);
    if (failure) return failure;
    try {
        const receipt = await getLastOnchainIndexerReconciliationReceipt();
        if (!receipt) {
            return Response.json(
                { error: "Completed on-chain indexer reconciliation is unavailable" },
                { status: 503, headers: NO_STORE }
            );
        }
        return Response.json(receipt, { headers: NO_STORE });
    } catch (error) {
        reportIndexerError("On-chain indexer health check failed", error);
        return Response.json(
            { error: "On-chain indexer health check failed" },
            { status: 503, headers: NO_STORE }
        );
    }
}

export async function POST(request: Request) {
    const failure = authorizationFailure(request);
    if (failure) return failure;
    const diagnosticRequested =
        new URL(request.url).searchParams.get("diagnostic") === "1";
    let diagnosticStage: OnchainIndexerDiagnosticStage = "request-parsing";
    const onDiagnosticStage = diagnosticRequested
        ? (stage: OnchainIndexerDiagnosticStage) => {
              diagnosticStage = stage;
          }
        : undefined;

    try {
        const parsed = await parseInternalReconcileRequest({
            request,
        });
        const force = parsed.legacy
            ? new URL(request.url).searchParams.get("force") === "1"
            : parsed.mode === "require-worker-run";
        const outcome = await runOnchainIndexerWorkerOnce({
            force,
            onDiagnosticStage,
        });
        observeIndexer(outcome);
        if (outcome.status === "reconciled") void protocolMetrics.refresh();
        const response = buildInternalReconcileResponse(outcome, parsed.legacy);
        const headers =
            response.retryAfter
                ? { ...NO_STORE, "Retry-After": response.retryAfter }
                : NO_STORE;
        return Response.json(response.body, {
            status: response.httpStatus,
            headers,
        });
    } catch (error) {
        observeMetrics(() => indexerRuns.inc({ outcome: "error" }));
        reportIndexerError("On-chain indexer worker failed", error);
        return Response.json(
            {
                error: "On-chain indexer worker failed",
                ...(diagnosticRequested
                    ? {
                          diagnostic: internalIndexerDiagnostic(error),
                          stage: diagnosticStage,
                      }
                    : {}),
            },
            { status: 503, headers: NO_STORE }
        );
    }
}
