import { createInterface } from "node:readline";
import { runRequest } from "./engine.ts";
import { MissingPoolState } from "./types.ts";
import type { PoolCoverage, SdkRequest } from "./types.ts";

const input = createInterface({ input: process.stdin, crlfDelay: Infinity });
const pending: SdkRequest[] = [];
const controllers = new Map<string | number, AbortController>();
const waiting = new Map<string | number, { resolve: (coverage: PoolCoverage[]) => void; reject: (error: Error) => void }>();
const continued = new Set<string | number>();
const abandoned = new Set<string | number>();
const jobs = new Map<string | number, Promise<void>>();
let pumping = false;
const reply = (value: unknown) => process.stdout.write(JSON.stringify(value) + "\n");
async function pump() {
  if (pumping) return;
  pumping = true;
  while (pending.length) {
    const request = pending.shift()!;
    await handle(request);
  }
  pumping = false;
}
async function handle(request: SdkRequest) {
  const controller = controllers.get(request.id)!;
  const load = (missing: MissingPoolState): Promise<PoolCoverage[]> => new Promise((resolve, reject) => {
    controller.signal.throwIfAborted();
    waiting.set(request.id, { resolve, reject });
    reply({ id: request.id, stateRequest: [{ poolId: missing.poolId,
      wordPositions: missing.wordPositions, ticks: missing.ticks }] });
  });
  try {
    controller.signal.throwIfAborted();
    const result = await runRequest(request, controller.signal, request.continueState ? load : undefined);
    // Only candidate-changing fields cross IPC. Coverage is unchanged and
    // already belongs to Python; sending every cached tick can exceed framing.
    const compactPool = (pool: Record<string, unknown>) => {
      const { ticks: _ticks, bitmapWords: _words, ...state } = pool;
      return state;
    };
    const postState = Array.isArray(result.postState)
      ? result.postState.map(pool => compactPool(pool as unknown as Record<string, unknown>))
      : compactPool(result.postState as unknown as Record<string, unknown>);
    if (!abandoned.has(request.id)) reply({ id: request.id, result: { ...result, postState } });
  } catch (error) {
    if (abandoned.has(request.id)) return;
    if (error instanceof MissingPoolState) reply({ id: request.id, missingState: [{
      poolId: error.poolId, wordPositions: error.wordPositions, ticks: error.ticks }] });
    else reply({ id: request.id, error: { code: controller.signal.aborted ? "CANCELLED" : "SDK_ERROR",
      message: error instanceof Error ? error.message : String(error) } });
  } finally {
    controllers.delete(request.id); waiting.delete(request.id);
    continued.delete(request.id); abandoned.delete(request.id);
  }
}
async function cancel(request: SdkRequest) {
  const controller = controllers.get(request.id);
  const job = jobs.get(request.id);
  if (continued.has(request.id)) {
    abandoned.add(request.id);
    const state = waiting.get(request.id);
    controllers.delete(request.id); waiting.delete(request.id);
    controller?.abort(); state?.reject(new Error("Cancelled"));
    await job;
  } else controller?.abort();
  if (request.acknowledge) reply({ id: request.id, cancelled: true });
}
input.on("line", line => {
  try {
    const request = JSON.parse(line) as SdkRequest;
    if (request.operation === "resume") {
      const state = waiting.get(request.id);
      if (!state) { reply({ id: request.id, error: { code: "SDK_ERROR", message: "Continuation unavailable" } }); return; }
      waiting.delete(request.id); state.resolve(request.coverage ?? []); return;
    }
    if (request.operation === "cancel") {
      void cancel(request); return;
    }
    controllers.set(request.id, new AbortController());
    if (request.continueState) {
      continued.add(request.id);
      const job = handle(request); jobs.set(request.id, job);
      void job.finally(() => jobs.delete(request.id));
    } else { pending.push(request); void pump(); }
  } catch (error) { reply({ error: { code: "INVALID_REQUEST", message: String(error) } }); }
});
