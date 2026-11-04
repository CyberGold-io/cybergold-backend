/** Request-owned callbacks for reusable JSONL calculation workers. */
type Callback = { resolve: (value: any) => void; reject: (error: Error) => void };
type Calculation = (request: any, quote: (value: any) => Promise<any>, publish: (candidates: any[]) => void) => Promise<any[]>;

export function createCalculationSession(calculate: Calculation, reply: (value: any) => void,
                                          failure: (error: unknown) => string) {
  const requests = new Map<string, { active: boolean; pending: Map<string, Callback> }>();
  let sequence = 0;
  let closed = false;
  const retire = (request: { active: boolean; pending: Map<string, Callback> }) => {
    request.active = false;
    for (const callback of request.pending.values()) callback.reject(new Error('Calculation request retired'));
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
      const request = { active: !closed, pending: new Map<string, Callback>() };
      requests.set(frame.id, request);
      const publish = (candidates: any[]) => {
        if (request.active) reply({ id: frame.id, operation: 'candidates', candidates });
      };
      const quote = (value: any): Promise<any> => new Promise((resolve, reject) => {
        if (!request.active) { reject(new Error('Calculation request retired')); return; }
        const quoteId = `${frame.id}:${++sequence}`;
        request.pending.set(quoteId, { resolve, reject });
        reply({ id: frame.id, operation: 'quote', quoteId, ...value });
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
