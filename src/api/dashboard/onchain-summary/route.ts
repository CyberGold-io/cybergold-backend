import { getOnchainDashboardSummary } from "@/server/onchain-indexer/indexer";
import { publicApiError } from "@/server/public-api-errors";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
    try {
        const summary = await getOnchainDashboardSummary();
        return Response.json(summary, {
            headers: {
                "Cache-Control": "public, max-age=10, stale-while-revalidate=20",
            },
        });
    } catch (error) {
        return publicApiError("Failed to load on-chain dashboard summary.", {
            context: "dashboard-onchain-summary",
            error,
        });
    }
}
