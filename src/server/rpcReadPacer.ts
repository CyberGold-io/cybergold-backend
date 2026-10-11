// The public sandbox charges 4 tokens per eth_call and refills at 40/s.
// Reserve 8/s for other reads. This paces contract reads in this server process;
// it is not a distributed limiter for indexers, wallets, or other app instances.
const ETH_CALL_COST = 4;
const CONTRACT_READ_TOKENS_PER_SECOND = 32;

type PendingRead = {
  calls: number;
  resolve: () => void;
  reject: (reason: unknown) => void;
  signal: AbortSignal;
  abort: () => void;
};

export class RpcReadPacer {
  private nextStart = 0;
  private pausedUntil = 0;
  private pending: PendingRead[] = [];
  private timer: ReturnType<typeof setTimeout> | undefined;

  wait(calls: number, signal: AbortSignal): Promise<void> {
    if (signal.aborted) return Promise.reject(signal.reason);
    return new Promise((resolve, reject) => {
      const entry: PendingRead = {
        calls, resolve, reject, signal,
        abort: () => {
          this.pending = this.pending.filter((item) => item !== entry);
          reject(signal.reason);
          this.drain();
        },
      };
      this.pending.push(entry);
      signal.addEventListener("abort", entry.abort, { once: true });
      this.drain();
    });
  }

  pause(delayMs: number) {
    this.pausedUntil = Math.max(this.pausedUntil, Date.now() + delayMs);
    this.drain();
  }

  private drain() {
    if (this.timer !== undefined) clearTimeout(this.timer);
    this.timer = undefined;
    if (this.pending.length === 0) return;
    const now = Date.now();
    const delay = Math.max(this.nextStart, this.pausedUntil) - now;
    if (delay > 0) {
      this.timer = setTimeout(() => this.drain(), Math.min(delay, 2_147_483_647));
      return;
    }
    const entry = this.pending.shift()!;
    entry.signal.removeEventListener("abort", entry.abort);
    this.nextStart = now + entry.calls * ETH_CALL_COST * 1000 / CONTRACT_READ_TOKENS_PER_SECOND;
    entry.resolve();
    this.drain();
  }
}

export function countContractReads(payload: unknown): number {
  return (Array.isArray(payload) ? payload : [payload]).filter(
    (call) => call && typeof call === "object" && call.method === "eth_call"
  ).length;
}

export function rpcRetryDelayMs(value: string | null, now = Date.now()): number {
  if (!value?.trim()) return 1_000;
  const seconds = /^\d+$/.test(value.trim()) ? Number(value) : undefined;
  const delay = seconds === undefined ? Date.parse(value) - now : seconds * 1000;
  return Number.isFinite(delay) ? Math.max(1_000, delay) : 1_000;
}

// Survive Next.js development reloads without creating a fresh budget each time.
const state = globalThis as typeof globalThis & { cyberGoldRpcReadPacer?: RpcReadPacer };
export function sandboxRpcReadPacer(upstream: URL) {
  if (upstream.origin !== "https://rpc.cybergold.io") return undefined;
  return state.cyberGoldRpcReadPacer ??= new RpcReadPacer();
}
