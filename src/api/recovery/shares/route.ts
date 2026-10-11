import { getRecoverySharePortfolio } from "@/server/recovery/rpcPortfolio";
import { handleRecoverySharesRequest } from "@/utils/recoverySharesApi";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  return handleRecoverySharesRequest(request, getRecoverySharePortfolio);
}
