import { createInterface } from "node:readline";
import { runRequest } from "./engine.ts";
import { MissingPoolState } from "./types.ts";
import type { SdkRequest } from "./types.ts";

const input = createInterface({ input: process.stdin, crlfDelay: Infinity });
const pending: SdkRequest[] = [];
const controllers = new Map<string | number, AbortController>();
let pumping = false;
const reply = (value: unknown) => process.stdout.write(JSON.stringify(value) + "\n");
async function pump() {
  if (pumping) return;
  pumping = true;
  while (pending.length) {
    const request = pending.shift()!;
    const controller = controllers.get(request.id)!;
    try {
      controller.signal.throwIfAborted();
      const result = await runRequest(request, controller.signal);
      // Only candidate-changing fields cross IPC. Coverage is unchanged and
      // already belongs to Python; sending every cached tick can exceed framing.
      const compactPool = (pool: Record<string, unknown>) => {
        const { ticks: _ticks, bitmapWords: _words, ...state } = pool;
        return state;
      };
      const postState = Array.isArray(result.postState)
        ? result.postState.map(pool => compactPool(pool as unknown as Record<string, unknown>))
        : compactPool(result.postState as unknown as Record<string, unknown>);
      reply({ id: request.id, result: { ...result, postState } });
    } catch (error) {
      if (error instanceof MissingPoolState) reply({ id: request.id, missingState: [{
        poolId: error.poolId, wordPositions: error.wordPositions, ticks: error.ticks }] });
      else reply({ id: request.id, error: { code: controller.signal.aborted ? "CANCELLED" : "SDK_ERROR",
        message: error instanceof Error ? error.message : String(error) } });
    } finally { controllers.delete(request.id); }
  }
  pumping = false;
}
input.on("line", line => {
  try {
    const request = JSON.parse(line) as SdkRequest;
    if (request.operation === "cancel") { controllers.get(request.id)?.abort(); return; }
    controllers.set(request.id, new AbortController());
    pending.push(request);
    void pump();
  } catch (error) { reply({ error: { code: "INVALID_REQUEST", message: String(error) } }); }
});
