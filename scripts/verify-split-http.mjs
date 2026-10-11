import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
const origin = process.argv[2] ?? 'http://127.0.0.1:3419';
const { fixtures } = JSON.parse(readFileSync('tests/contracts/next-baseline.json', 'utf8'));
const names = ['content-type', 'cache-control', 'allow', 'retry-after', 'x-cybergold-faucet-request-id'];
for (const { request, response: expected } of fixtures) {
 const response = await fetch(new URL(request.path, origin), { method: request.method, headers: request.headers,
  ...(request.body === undefined ? {} : { body: new TextEncoder().encode(request.body) }), redirect: 'manual' });
 let body = await response.text();
 try { const parsed = JSON.parse(body); if(parsed?.correlationId) { parsed.correlationId = '<correlation-id>'; body = JSON.stringify(parsed); } } catch {}
 assert.deepEqual({ status: response.status, headers: Object.fromEntries(names.filter(name=>response.headers.has(name)).map(name=>[name,response.headers.get(name)])), body }, expected, JSON.stringify(request));
}
for (const path of ['/api/internal/onchain-indexer/reconcile', '/api/internal/onchain-indexer/fork-generation', '/api/internal%2Fonchain-indexer%2Freconcile']) {
 const response = await fetch(new URL(path, origin), { method: 'POST', body: '{}' });
 assert.equal(response.status, 404, path);
}
console.log(`${fixtures.length} production baseline cases match through frontend/backend; worker paths are absent.`);
