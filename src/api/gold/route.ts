import { goldMarketData } from "../../server/market-cache";

export const dynamic = "force-dynamic";

export async function GET() {
  const resolution = await goldMarketData();
  const remaining = Math.max(0, Math.floor((1_800_000 -
    Math.max(0, Date.now() - Date.parse(resolution.payload.fetchedAt))) / 1000));

  return Response.json(resolution.payload, {
    headers: {
      "Cache-Control": resolution.isFresh && remaining > 0
        ? `s-maxage=${remaining}, stale-while-revalidate=1800`
        : "no-store",
    },
  });
}
