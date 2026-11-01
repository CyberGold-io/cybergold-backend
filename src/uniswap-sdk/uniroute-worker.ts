/** Enumeration child using the managed supplier JSONL protocol; no RPC/prices. */
import { createInterface } from 'node:readline';
import { discoverLocal } from './uniroute-local.ts';
const input = createInterface({ input: process.stdin, crlfDelay: Infinity });
input.on('line', line => {
  let request: any;
  try { request = JSON.parse(line); }
  catch { process.stdout.write(JSON.stringify({ error: 'Invalid UniRoute frame' })+'\n'); return; }
  void discoverLocal(request).then(candidates => {
    process.stdout.write(JSON.stringify({ id: request.id, candidates })+'\n');
  }, () => {
    process.stdout.write(JSON.stringify({ id: request.id, error: 'UniRoute discovery unavailable' })+'\n');
  });
});
