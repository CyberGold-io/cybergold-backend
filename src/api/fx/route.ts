import { fxMarketData } from "../../server/market-cache";

export const revalidate = 300;

export async function GET() {
  const resolution = await fxMarketData();

  return Response.json(resolution.payload, {
    headers: {
      "Cache-Control": resolution.isFresh
        ? "s-maxage=300, stale-while-revalidate=300"
        : "no-store",
    },
  });
}
