/** Bounded callback production; quote economics and result indices stay unchanged. */
export const CALLBACK_CREDITS = 8;

type Waiting = { resolve: () => void; signal: AbortSignal; abort: () => void };

/** One driver's response-outstanding window, shared by every calculation. */
export class CallbackCredits {
  private available = CALLBACK_CREDITS;
  private waiting = new Map<Waiting, Waiting>();

  private async acquire(signal: AbortSignal) {
    signal.throwIfAborted();
    if (this.available) { this.available--; return; }
    await new Promise<void>((resolve, reject) => {
      const waiter: Waiting = { resolve, signal, abort: () => {
        this.waiting.delete(waiter);
        reject(signal.reason);
      } };
      this.waiting.set(waiter, waiter);
      signal.addEventListener('abort', waiter.abort, { once: true });
    });
  }

  private release() {
    const waiter = this.waiting.values().next().value;
    if (waiter) {
      this.waiting.delete(waiter);
      waiter.signal.removeEventListener('abort', waiter.abort);
      waiter.resolve();
    } else this.available++;
  }

  async run<T>(signal: AbortSignal, produce: () => Promise<T>): Promise<T> {
    await this.acquire(signal);
    try {
      // A grant can be followed by retirement before this continuation resumes.
      signal.throwIfAborted();
      return await produce();
    } finally { this.release(); }
  }
}

export type QuoteCallback<Request = any, Response = any> = ((value: Request) => Promise<Response>) & {
  signal?: AbortSignal;
  request?: (build: () => Request) => Promise<Response>;
};

/** Framed workers build payloads only after admission; direct callers keep their API. */
export function requestQuote<Request, Response>(quote: QuoteCallback<Request, Response>, build: () => Request) {
  return quote.request ? quote.request(build) : quote(build());
}

/** Pull finite matrix indices lazily instead of constructing one Promise per job. */
export async function mapQuoteJobs<T>(count: number, job: (index: number) => Promise<T>, signal?: AbortSignal): Promise<T[]> {
  const results = new Array<T>(count);
  let next = 0, failed = false;
  const worker = async () => {
    while (next < count && !failed) {
      try {
        signal?.throwIfAborted();
        const index = next++;
        results[index] = await job(index);
      } catch (error) {
        failed = true;
        throw error;
      }
    }
  };
  await Promise.all(Array.from({ length: Math.min(count, CALLBACK_CREDITS) }, worker));
  return results;
}
