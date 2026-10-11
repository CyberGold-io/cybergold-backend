import { getCoreActivity } from "../../../server/onchain-indexer/coreActivity";
import { publicApiError } from "../../../server/public-api-errors";

export async function GET() {
  try {
    return Response.json(await getCoreActivity(), { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    return publicApiError("Protocol activity is temporarily unavailable.", { context: "core-activity", error });
  }
}
