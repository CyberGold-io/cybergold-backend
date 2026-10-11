import { mock } from 'node:test';
import { RpcReadPacer, rpcRetryDelayMs } from '../../src/server/rpcReadPacer';

const results:any={};
mock.timers.enable({apis:['Date','setTimeout'],now:1000});
try {
  const pacer=new RpcReadPacer();
  const starts:number[]=[];
  const waits=[5,2,5].map(count=>pacer.wait(count,new AbortController().signal).then(()=>starts.push(Date.now())));
  await Promise.resolve();
  mock.timers.tick(625); await Promise.resolve();
  mock.timers.tick(250); await Promise.all(waits);
  results.budgetStarts=starts;
} finally { mock.timers.reset(); }
mock.timers.enable({apis:['Date','setTimeout'],now:1000});
try {
  const pacer=new RpcReadPacer();
  await pacer.wait(5,new AbortController().signal);
  let start:number|null=null;
  const queued=pacer.wait(5,new AbortController().signal).then(()=>start=Date.now());
  pacer.pause(2000);
  mock.timers.tick(1999); await Promise.resolve();
  results.queuedDuringCooldown=start;
  mock.timers.tick(1); await queued;
  results.cooldownStart=start;
} finally { mock.timers.reset(); }
mock.timers.enable({apis:['Date','setTimeout'],now:1000});
try {
  const pacer=new RpcReadPacer();
  await pacer.wait(5,new AbortController().signal);
  const cancel=new AbortController();
  let cancelled=false;
  const discarded=pacer.wait(5,cancel.signal).catch(()=>cancelled=true);
  let start:number|null=null;
  const following=pacer.wait(1,new AbortController().signal).then(()=>start=Date.now());
  cancel.abort(); await discarded;
  mock.timers.tick(625); await following;
  results.cancelled=cancelled; results.afterCancelStart=start;
} finally { mock.timers.reset(); }
const now=Date.parse('2026-09-30T10:00:00Z');
results.retryDelays=[null,'','invalid','0','1','2',' 2 ','1.5','Wed, 30 Sep 2026 10:00:03 GMT','Wed, 30 Sep 2026 09:59:00 GMT',
 '2026-09-30T10:00:03Z',' 2026-09-30T10:00:03Z ','Sep 30 2026 10:00:03 GMT','9/30/2026 10:00:03 GMT','\u0085 2','\ufeff2']
  .map(value=>({value,delay:rpcRetryDelayMs(value,now)}));
process.stdout.write(JSON.stringify(results)+'\n');
