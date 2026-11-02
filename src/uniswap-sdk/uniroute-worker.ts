/** Owned published UniRoute finder + quote/split JSONL calculation child. */
import { createInterface } from 'node:readline';
import { pathToFileURL } from 'node:url';
import { discoverDeepLocal } from './uniroute-deep.ts';
import { createCalculationSession } from './calculation-session.ts';

export function main() {
const input = createInterface({ input: process.stdin, crlfDelay: Infinity });
const reply = (frame: any) => process.stdout.write(JSON.stringify(frame)+'\n');
// Constructor command overrides select finite comparison variants; serving's
// default is deep5. No environment gate or public RouteQuery field is added.
const options = { finderOnly: process.argv.includes('--finder-only'),
  percentageStep: process.argv.includes('--split-percentage=25') ? 25 as const : 5 as const };
const session = createCalculationSession((request, quote, publish) =>
  discoverDeepLocal(request, quote, publish, options), reply, () => 'UniRoute discovery unavailable');
input.on('line', line => {
  try { session.receive(JSON.parse(line)); }
  catch { reply({ error: 'Invalid UniRoute frame' }); return; }
});
input.on('close', () => session.close());
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) main();
