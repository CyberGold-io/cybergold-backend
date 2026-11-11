/** Request-owned callbacks for reusable JSONL calculation workers. */
import { CallbackCredits } from './callback-work.ts';
import type { QuoteCallback } from './callback-work.ts';
type Callback = { resolve: (value: any) => void; reject: (error: Error) => void };
type Calculation = (request: any, quote: QuoteCallback, publish: (candidates: any[]) => void) => Promise<any[]>;
type Request = { active: boolean; pending: Map<string, Callback>; controller: AbortController };

export function createCalculationSession(calculate: Calculation, reply: (value: any) => void,
                                          failure: (error: unknown) => string) {
  const requests = new Map<string, Request>();
  const credits = new CallbackCredits();
  let sequence = 0;
  let closed = false;
  const retire = (request: Request) => {
    request.active = false;
    const error = new Error('Calculation request retired');
    request.controller.abort(error);
    for (const callback of request.pending.values()) callback.reject(error);
    request.pending.clear();
  };
  return {
    receive(frame: any) {
      if (frame.operation === 'cancel') {
        const request = requests.get(frame.id);
        if (request) retire(request);
        requests.delete(frame.id);
        // Python drains this query's callback writers before cancel. No late
        // quoteResult can follow it, and retired calculations cannot publish.
        reply({ id: frame.id, operation: 'cancelled' });
        return true;
      }
      if (frame.operation === 'quoteResult') {
        const request = requests.get(frame.id);
        // A retired request may already have sent callbacks before its terminal
        // error. Their late results cannot enter the next request's exchange.
        if (request && !request.active) return true;
        const callback = request?.pending.get(frame.quoteId);
        if (!callback) return false;
        request!.pending.delete(frame.quoteId);
        callback.resolve(frame.result);
        return true;
      }
      const request = { active: !closed, pending: new Map<string, Callback>(), controller: new AbortController() };
      if (closed) request.controller.abort(new Error('Calculation request retired'));
      requests.set(frame.id, request);
      const publish = (candidates: any[]) => {
        if (request.active) reply({ id: frame.id, operation: 'candidates', candidates });
      };
      const quote: QuoteCallback = (value: any) => quote.request!(() => value);
      quote.signal = request.controller.signal;
      quote.request = build => credits.run(request.controller.signal, async () => {
        const value = build();
        request.controller.signal.throwIfAborted();
        const quoteId = `${frame.id}:${++sequence}`;
        try {
          return await new Promise((resolve, reject) => {
            request.pending.set(quoteId, { resolve, reject });
            reply({ id: frame.id, operation: 'quote', quoteId, ...value });
          });
        } finally { request.pending.delete(quoteId); }
      });
      const finish = (value: any) => {
        if (!request.active) return;
        retire(request);
        reply({ id: frame.id, ...value });
      };
      void calculate(frame, quote, publish).then(candidates => finish({ candidates }),
        error => finish({ error: failure(error) }));
      return true;
    },
    close() {
      closed = true;
      for (const request of requests.values()) retire(request);
      requests.clear();
    },
  };
}
