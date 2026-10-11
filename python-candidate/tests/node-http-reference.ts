import { createBackendServer } from "../../src/http-server";

const stamp = "2026-09-30T10:00:00.000Z";
const app = await createBackendServer("api", { logger: false });
const NativeDate = Date;
globalThis.Date = class extends NativeDate {
  constructor(value?: any) { super(value ?? stamp); }
  static now() { return NativeDate.parse(stamp); }
} as DateConstructor;
const counts = { gold: 0, fx: 0 };
globalThis.fetch = (async (url) => {
  const feed = String(url).includes("PAXG") ? "gold" : "fx";
  const attempt = ++counts[feed];
  if (attempt === 1) return new Response("{}", { status: 503 });
  if (attempt === 2) return Response.json({ extra: true });
  if (attempt === 3) throw new Error("Fixture disconnected");
  return Response.json(feed === "gold" ? { symbol: "PAXGUSDT", price: "3800.25" }
    : { amount: 1, base: "USD", date: "2026-09-30", rates: { EUR: .86, CHF: .79, RUB: 82 } });
}) as typeof fetch;
try {
  const results = [];
  for (const feed of ["gold", "fx"] as const) {
    for (let index = 0; index < 6; index++) {
      const response = await app.inject({ method: "GET", url: `/api/${feed}` });
      results.push({ feed, index, status: response.statusCode, body: response.json(),
        contentType: response.headers["content-type"], cacheControl: response.headers["cache-control"],
        providerCalls: counts[feed] });
    }
    const head = await app.inject({ method: "HEAD", url: `/api/${feed}` });
    results.push({ feed, method: "HEAD", status: head.statusCode, body: head.body,
      contentType: head.headers["content-type"], cacheControl: head.headers["cache-control"],
      providerCalls: counts[feed] });
  }
  process.stdout.write(JSON.stringify(results) + "\n");
} finally {
  globalThis.Date = NativeDate;
  await app.close();
}
