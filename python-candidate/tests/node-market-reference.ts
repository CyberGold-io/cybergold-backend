// Compare against the retained implementation, not a second test-only port.
import { readFile } from "node:fs/promises";
import {
  parseGoldProviderPrice, parseFxProviderRates,
  parseGoldMarketDataPayload, parseFxMarketDataPayload,
  resolveGoldMarketData, resolveFxMarketData,
} from "../../src/utils/marketDataValidation";

const cases = JSON.parse(await readFile(new URL("../fixtures/market.json", import.meta.url), "utf8"));
const parsers = {
  goldProvider: parseGoldProviderPrice, fxProvider: parseFxProviderRates,
  goldPayload: parseGoldMarketDataPayload, fxPayload: parseFxMarketDataPayload,
};
const results = [];
for (const fixture of cases) {
  let result;
  if (fixture.kind === "resolve") {
    const resolver = fixture.feed === "gold" ? resolveGoldMarketData : resolveFxMarketData;
    const requests: string[] = [];
    result = await resolver(fixture.lastKnown, {
      now: () => new Date(fixture.now),
      fetchImpl: (async (url, options) => {
        requests.push(String(url));
        if (!(options?.signal instanceof AbortSignal)) throw new Error("Provider timeout missing");
        if (fixture.error) throw new Error("Fixture transport failure");
        return new Response(JSON.stringify(fixture.value), { status: fixture.status });
      }) as typeof fetch,
    });
    result = { ...result, requests };
  } else {
    result = parsers[fixture.kind as keyof typeof parsers](fixture.value) ?? null;
  }
  results.push({ name: fixture.name, result });
}
process.stdout.write(JSON.stringify(results) + "\n");
