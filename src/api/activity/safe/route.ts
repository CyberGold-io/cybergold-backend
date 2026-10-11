import { getSafeActivity } from "../../../server/safe-events/activity";
import { publicApiError } from "../../../server/public-api-errors";

export async function GET() {
  try {
    return Response.json(await getSafeActivity(), { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    return publicApiError("Safe activity is temporarily unavailable.", { context: "safe-activity", error });
  }
}
