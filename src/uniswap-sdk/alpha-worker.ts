/** Session-owned JSONL AlphaRouter. RPC and all swap arithmetic stay in Python. */
import { createInterface } from "node:readline";
import { pathToFileURL } from "node:url";
import { createAlphaRouter } from "./alpha-provider.ts";

const ZERO = "0x0000000000000000000000000000000000000000";
const WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2";

type Request = { id: string; chainId: number; blockNumber: number; source: string; target: string;
  amount: string; mode?: "exactIn" | "exactOut"; pools: any[] };

export function forwardHops(router: any, pools: any[], source: string, target: string) {
  let current = source.toLowerCase();
  const hops: any[] = [];
  const transition = (following: string) => {
    hops.push({ kind: current === ZERO ? "wrap" : "unwrap", currencyOut: following });
    current = following;
  };
  for (const sdkPool of pools) {
    const pool = router.poolSnapshot(sdkPool);
    if (!pool) {
      const fake = router.sdk.sor.V4_ETH_WETH_FAKE_POOL[Number(sdkPool.chainId)];
      if (sdkPool !== fake) throw new Error("AlphaRouter route pool unavailable");
      transition(current === ZERO ? WETH : ZERO);
      continue;
    }
    const a = pool.token0.address.toLowerCase(), b = pool.token1.address.toLowerCase();
    if (current === ZERO && a !== ZERO && b !== ZERO) transition(WETH);
    if (current === WETH && a !== WETH && b !== WETH && (a === ZERO || b === ZERO)) transition(ZERO);
    if (current !== a && current !== b) throw new Error("AlphaRouter route is disconnected");
    const zeroForOne = current === a;
    hops.push({ pool, zeroForOne });
    current = zeroForOne ? b : a;
  }
  if (current === ZERO && target.toLowerCase() === WETH) transition(WETH);
  if (current === WETH && target.toLowerCase() === ZERO) transition(ZERO);
  if (current !== target.toLowerCase()) throw new Error("AlphaRouter route output differs");
  return hops;
}

export async function routeRequest(request: Request, quote: (value: any) => Promise<any>) {
  let adapter: ReturnType<typeof createAlphaRouter>;
  adapter = createAlphaRouter({ chainId: request.chainId, blockNumber: request.blockNumber, pools: request.pools,
    quoteRoute: async ({ route, amount, mode }) => {
      const hops = forwardHops(adapter, route.pools ?? route.pairs, request.source, request.target);
      const result = await quote({ mode, amount: amount.quotient.toString(),
        branches: [{ amountIn: mode === "exactIn" ? amount.quotient.toString() : "0", hops }] });
      return { quote: result.quote, gasEstimate: "0",
        sqrtPriceX96AfterList: [], initializedTicksCrossedList: [] };
    } });
  const token = (address: string) => adapter.currency(request.pools.flatMap(pool => [pool.token0, pool.token1])
    .find(value => value.address.toLowerCase() === address.toLowerCase()) ?? { address, chainId: request.chainId, decimals: 18 });
  const input = token(request.source), output = token(request.target);
  const exactIn = request.mode !== "exactOut";
  const protocols = [...new Set(request.pools.map(pool => adapter.sdk.router.Protocol[pool.protocol.toUpperCase()]))];
  if (protocols.length > 1) protocols.push(adapter.sdk.router.Protocol.MIXED);
  const value = await adapter.router.route(adapter.sdk.core.CurrencyAmount.fromRawAmount(exactIn ? input : output,
    request.amount), exactIn ? output : input,
    exactIn ? adapter.sdk.core.TradeType.EXACT_INPUT : adapter.sdk.core.TradeType.EXACT_OUTPUT,
    undefined, { blockNumber: request.blockNumber, protocols });
  if (!value) return [];
  return [value.route.map((entry: any) => ({ amountIn: exactIn ? entry.amount.quotient.toString() : entry.quote.quotient.toString(),
    hops: forwardHops(adapter, entry.route.pools ?? entry.route.pairs, request.source, request.target) }))];
}

function main() {
  const input = createInterface({ input: process.stdin, crlfDelay: Infinity });
  const pending = new Map<string, { resolve: (value: any) => void; reject: (error: Error) => void }>();
  let sequence = 0;
  const reply = (value: any) => process.stdout.write(JSON.stringify(value) + "\n");
  input.on("line", line => {
    try {
      const frame = JSON.parse(line);
      if (frame.operation === "quoteResult") {
        const operation = pending.get(frame.quoteId);
        if (!operation) throw new Error("AlphaRouter callback unavailable");
        pending.delete(frame.quoteId);
        operation.resolve(frame.result);
        return;
      }
      const request = frame as Request;
      const quote = (value: any): Promise<any> => new Promise((resolve, reject) => {
        const quoteId = `${request.id}:${++sequence}`;
        pending.set(quoteId, { resolve, reject });
        reply({ id: request.id, operation: "quote", quoteId, ...value });
      });
      void routeRequest(request, quote).then(candidates => reply({ id: request.id, candidates }),
        error => reply({ id: request.id, error: error instanceof Error ? error.message : "AlphaRouter unavailable" }));
    } catch (_error) {
      reply({ error: "Invalid AlphaRouter frame" });
    }
  });
  input.on("close", () => {
    for (const operation of pending.values()) operation.reject(new Error("AlphaRouter input closed"));
  });
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) main();
