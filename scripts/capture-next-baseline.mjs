import { writeFileSync } from 'node:fs';
const origin = process.argv[2] ?? 'http://127.0.0.1:3417';
const publicGets = ['dashboard/onchain-summary', 'recovery/shares', 'gold', 'fx'];
const publicPosts = ['rpc', 'governance/owner-aliases', 'quote-pool-cache', 'safe', 'safe/events', 'faucet'];
const cases = [];
for (const path of [...publicGets, ...publicPosts]) {
  for (const method of ['OPTIONS', 'PUT', ...(publicPosts.includes(path) ? ['GET', 'HEAD'] : [])]) {
    cases.push({ path: `/api/${path}`, method });
  }
}
for (const path of publicPosts) {
  for (const body of ['{bad', 'null', '[]', '1', '"text"', '{}']) {
    cases.push({ path: `/api/${path}`, method: 'POST', body, headers: { 'Content-Type': 'application/json' } });
  }
  cases.push({ path: `/api/${path}`, method: 'POST', body: '{}' });
}
cases.push(
  { path: '/api/dashboard/onchain-summary', method: 'GET' },
  { path: '/api/dashboard/onchain-summary', method: 'HEAD' },
  { path: '/api/recovery/shares', method: 'GET' },
  { path: '/api/recovery/shares?holder=bad', method: 'GET' },
  { path: '/api/rpc', method: 'POST', body: '{"jsonrpc":"2.0","id":8,"method":"eth_sendRawTransaction","params":[]}' },
  { path: '/api/safe', method: 'POST', body: '{"action":"safe-info","safeAddress":"0x00000000000000000000000000000000000000a1"}' },
  { path: '/api/safe/events', method: 'POST', body: '{"safeAddress":"0x00000000000000000000000000000000000000a1","safeTxHashes":[]}' },
);
const headersToKeep = ['content-type', 'cache-control', 'allow', 'retry-after', 'x-cybergold-faucet-request-id'];
const fixtures = [];
for (const request of cases) {
  const headers = { ...request.headers };
  // fetch adds text/plain for string bodies; an explicit stream preserves a genuinely absent content type.
  const response = await fetch(new URL(request.path, origin), {
    method: request.method, headers,
    ...(request.body === undefined ? {} : { body: new TextEncoder().encode(request.body) }),
    redirect: 'manual',
  });
  let body = await response.text();
  try { const parsed = JSON.parse(body); if (parsed?.correlationId) { parsed.correlationId = '<correlation-id>'; body = JSON.stringify(parsed); } } catch {}
  fixtures.push({ request, response: { status: response.status,
    headers: Object.fromEntries(headersToKeep.filter(name => response.headers.has(name)).map(name => [name, response.headers.get(name)])), body } });
}
writeFileSync('tests/contracts/next-baseline.json', JSON.stringify({
  source: { repository: 'CyberGold-io/cybergold-app', commit: 'b3f4d790801882b14509a2ec6a2ca770b6c93b53', next: '16.3.5', mode: 'production', environment: 'tests/fixtures/app.env' }, fixtures,
}, null, 2) + '\n');
console.log(`Captured ${fixtures.length} production HTTP responses.`);
