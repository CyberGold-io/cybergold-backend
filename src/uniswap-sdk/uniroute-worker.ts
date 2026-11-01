/** Owned published UniRoute finder + quote/split JSONL calculation child. */
import { createInterface } from 'node:readline';
import { pathToFileURL } from 'node:url';
import { discoverDeepLocal } from './uniroute-deep.ts';

export function main() {
const input = createInterface({ input: process.stdin, crlfDelay: Infinity });
const pending = new Map<string, { resolve: (result: any) => void; reject: (error: Error) => void }>();
let sequence = 0;
let closed = false;
const reply = (frame: any) => process.stdout.write(JSON.stringify(frame)+'\n');
// Constructor command overrides select finite comparison variants; serving's
// default is deep5. No environment gate or public RouteQuery field is added.
const options = { finderOnly: process.argv.includes('--finder-only'),
  percentageStep: process.argv.includes('--split-percentage=25') ? 25 as const : 5 as const };
input.on('line', line => {
  let request: any;
  try { request = JSON.parse(line); }
  catch { reply({ error: 'Invalid UniRoute frame' }); return; }
  if (request.operation === 'quoteResult') {
    const callback = pending.get(request.quoteId);
    if (callback) { pending.delete(request.quoteId); callback.resolve(request.result); }
    return;
  }
  const quote = (frame: any): Promise<any> => new Promise((resolve, reject) => {
    if (closed) { reject(new Error('UniRoute input closed')); return; }
    const quoteId = `${request.id}:${++sequence}`;
    pending.set(quoteId, { resolve, reject });
    reply({ id: request.id, operation: 'quote', quoteId, ...frame });
  });
  void discoverDeepLocal(request, quote, candidates => { reply({ id: request.id, operation: 'candidates', candidates }); }, options)
    .then(candidates => reply({ id: request.id, candidates }),
      () => reply({ id: request.id, error: 'UniRoute discovery unavailable' }));
});
input.on('close', () => {
  closed = true;
  for (const callback of pending.values()) callback.reject(new Error('UniRoute input closed'));
  pending.clear();
});
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) main();
