import test from 'node:test';
import assert from 'node:assert/strict';
import { setImmediate } from 'node:timers/promises';
import { CallbackCredits, mapQuoteJobs, requestQuote } from '../src/uniswap-sdk/callback-work.ts';
import { createCalculationSession } from '../src/uniswap-sdk/calculation-session.ts';

function deferred<T = void>() {
  let resolve!: (value: T) => void, reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

async function until(predicate: () => boolean) {
  while (!predicate()) await setImmediate();
}

test('lazy matrix pulls eight jobs, progresses independently and preserves every result index', { timeout: 5000 }, async () => {
  const gates = Array.from({ length: 25 }, () => deferred<number>());
  const started: number[] = [];
  const operation = mapQuoteJobs(gates.length, async index => {
    started.push(index);
    return await gates[index].promise;
  });
  try {
    assert.deepEqual(started, [0, 1, 2, 3, 4, 5, 6, 7]);
    gates[7].resolve(70);
    await until(() => started.length === 9);
    assert.deepEqual(started, [0, 1, 2, 3, 4, 5, 6, 7, 8]);
    assert(!started.includes(9), 'one completed job permits one additional payload construction');
    for (let index = gates.length-1; index >= 0; index--) gates[index].resolve(index*10);
    assert.deepEqual(await operation, Array.from({ length: 25 }, (_, index) => index*10));
    assert.deepEqual(started, Array.from({ length: 25 }, (_, index) => index));
    let emptyCalls = 0;
    assert.deepEqual(await mapQuoteJobs(0, async () => ++emptyCalls), []);
    assert.equal(emptyCalls, 0);
  } finally {
    for (let index = 0; index < gates.length; index++) gates[index].resolve(index*10);
    await operation;
  }
});

test('a first job error propagates before held peers finish and stops constructing the tail', { timeout: 5000 }, async () => {
  const held = deferred<number>(), failed = deferred<number>();
  const started: number[] = [];
  const operation = mapQuoteJobs(40, async index => {
    started.push(index);
    return index === 0 ? failed.promise : held.promise;
  });
  const rejected = assert.rejects(operation, /fixture timeout/);
  failed.reject(new Error('fixture timeout'));
  try {
    await rejected;
    assert.equal(started.length, 8, 'ordinary error must not wait for another held callback or build its tail');
  } finally { held.resolve(1); }
});

test('credit grant followed by owner cancellation emits no work and returns capacity exactly once', { timeout: 5000 }, async () => {
  const credits = new CallbackCredits(), owner = new AbortController();
  const gates = Array.from({ length: 8 }, () => deferred<number>());
  let entered = 0;
  const active = gates.map(gate => credits.run(owner.signal, async () => { entered++; return gate.promise; }));
  await until(() => entered === 8);
  const cancelled = new AbortController();
  let cancelledBuilds = 0;
  const stopped = credits.run(cancelled.signal, async () => { cancelledBuilds++; return 9; });
  const rejected = assert.rejects(stopped, /cancelled after grant/);
  await until(() => (credits as any).waiting.size === 1);
  // Intercept only the grant event: cancellation occurs after resolution and
  // before the queued owner's continuation, not during active IO.
  const waiter = (credits as any).waiting.values().next().value;
  const grant = waiter.resolve;
  waiter.resolve = () => { grant(); cancelled.abort(new Error('cancelled after grant')); };
  gates[0].resolve(0);
  await rejected;
  assert.equal(cancelledBuilds, 0);
  let replacementStarted = false, overflowStarted = false;
  const replacement = deferred<number>();
  const one = credits.run(owner.signal, async () => { replacementStarted = true; return replacement.promise; });
  await until(() => replacementStarted);
  const two = credits.run(owner.signal, async () => { overflowStarted = true; return 2; });
  await until(() => (credits as any).waiting.size === 1);
  assert.equal(overflowStarted, false, 'a cancelled grant must not create a ninth credit');
  for (const gate of gates) gate.resolve(1);
  replacement.resolve(1);
  await Promise.all([...active, one, two]);
  assert.equal(overflowStarted, true);
});

test('queued owners withdraw without consuming capacity or disturbing surviving FIFO work', { timeout: 5000 }, async () => {
  const credits = new CallbackCredits(), activeOwner = new AbortController();
  const gates = Array.from({ length: 8 }, () => deferred<number>());
  let activeCount = 0;
  const active = gates.map(gate => credits.run(activeOwner.signal, async () => { activeCount++; return gate.promise; }));
  await until(() => activeCount === 8);
  const cancelled = new AbortController(), keep = new AbortController();
  const order: string[] = [];
  const retired = credits.run(cancelled.signal, async () => { order.push('retired'); });
  const retiredResult = assert.rejects(retired, /withdrawn/);
  const first = credits.run(keep.signal, async () => { order.push('first'); });
  const second = credits.run(keep.signal, async () => { order.push('second'); });
  cancelled.abort(new Error('withdrawn'));
  await retiredResult;
  assert.equal((credits as any).waiting.size, 2);
  gates[0].resolve(0);
  await Promise.all([first, second]);
  assert.deepEqual(order, ['first', 'second']);
  for (const gate of gates) gate.resolve(0);
  await Promise.all(active);
});

test('one driver shares eight callbacks across calculations while hints and cancellation still progress', { timeout: 5000 }, async () => {
  const frames: any[] = [], built: { id: string; index: number }[] = [];
  const session = createCalculationSession(async (request, quote, publish) => {
    publish([[request.id, 'finder']]);
    const results = await mapQuoteJobs(request.jobs, index => requestQuote(quote, () => {
      built.push({ id: request.id, index });
      return { amount: String(index), branchIdentity: `${request.id}:${index}` };
    }), quote.signal);
    return results.map(result => [result.quote]);
  }, frame => { frames.push(frame); }, error => (error as Error).message);
  try {
    session.receive({ id: 'held', jobs: 40 });
    await until(() => frames.filter(frame => frame.operation === 'quote').length === 8);
    session.receive({ id: 'sibling', jobs: 12 });
    session.receive({ id: 'no-price-finder', jobs: 0 });
    await until(() => frames.some(frame => frame.id === 'no-price-finder' && !frame.operation));
    assert.equal(built.length, 8, 'waiting calculation payload factories must not run before shared credit');
    assert(frames.some(frame => frame.id === 'sibling' && frame.operation === 'candidates'));
    assert.equal(frames.filter(frame => frame.operation === 'quote').length, 8);
    session.receive({ id: 'held', operation: 'cancel' });
    assert.deepEqual(frames.at(-1), { id: 'held', operation: 'cancelled' });
    await until(() => frames.filter(frame => frame.id === 'sibling' && frame.operation === 'quote').length === 8);
    const answered = new Set<string>();
    while (!frames.some(frame => frame.id === 'sibling' && !frame.operation)) {
      const pending = frames.filter(frame => frame.id === 'sibling' && frame.operation === 'quote' && !answered.has(frame.quoteId));
      assert(pending.length <= 8);
      // Replies in reverse completion order must not permute result indices.
      for (const frame of pending.reverse()) {
        answered.add(frame.quoteId);
        assert.equal(session.receive({ id: frame.id, operation: 'quoteResult', quoteId: frame.quoteId,
          result: { quote: frame.amount } }), true);
      }
      await setImmediate();
    }
    assert.equal(built.filter(row => row.id === 'held').length, 8);
    assert.equal(built.filter(row => row.id === 'sibling').length, 12);
    assert.deepEqual(frames.find(frame => frame.id === 'sibling' && !frame.operation).candidates,
      Array.from({ length: 12 }, (_, index) => [String(index)]));
    assert(!frames.some(frame => frame.id === 'held' && !frame.operation));
  } finally { session.close(); await setImmediate(); }
});

test('terminal job failure retires held peers and frees all eight credits for the next owner', { timeout: 5000 }, async () => {
  const frames: any[] = [], built: string[] = [];
  const session = createCalculationSession(async (request, quote) => {
    return mapQuoteJobs(32, index => requestQuote(quote, () => {
      built.push(`${request.id}:${index}`);
      if (request.id === 'failed' && index === 8) throw new Error('fixture callback timeout');
      return { amount: String(index) };
    }), quote.signal);
  }, frame => { frames.push(frame); }, error => (error as Error).message);
  try {
    session.receive({ id: 'failed' });
    await until(() => frames.length === 8);
    const first = frames[0];
    session.receive({ id: first.id, operation: 'quoteResult', quoteId: first.quoteId, result: { quote: '1' } });
    await until(() => frames.some(frame => frame.error));
    assert.deepEqual(frames.at(-1), { id: 'failed', error: 'fixture callback timeout' });
    assert.equal(frames.filter(frame => frame.operation === 'quote').length, 8,
      'the other seven callbacks remain unanswered; error retirement must not await them');
    assert.equal(built.length, 9);
    session.receive({ id: 'next' });
    await until(() => frames.filter(frame => frame.id === 'next' && frame.operation === 'quote').length === 8);
    assert.equal(built.filter(row => row.startsWith('failed:')).length, 9);
    assert.equal(built.filter(row => row.startsWith('next:')).length, 8);
  } finally { session.close(); await setImmediate(); }
});

test('input close retires active and queued calculations without late payloads or terminal frames', { timeout: 5000 }, async () => {
  const frames: any[] = [], built: string[] = [];
  let finished = 0;
  const session = createCalculationSession(async (request, quote, publish) => {
    try {
      return await mapQuoteJobs(24, index => requestQuote(quote, () => {
        built.push(`${request.id}:${index}`); return { amount: String(index) };
      }), quote.signal);
    } finally { finished++; publish([['late retired finder']]); }
  }, frame => { frames.push(frame); }, () => 'ordinary failure');
  session.receive({ id: 'first' });
  session.receive({ id: 'second' });
  await until(() => frames.length === 8);
  session.close();
  await until(() => finished === 2);
  assert.equal(frames.length, 8);
  assert.equal(built.length, 8);
  assert(frames.every(frame => frame.operation === 'quote'));
});

test('independent driver sessions each retain eight response-outstanding callbacks', { timeout: 5000 }, async () => {
  const frames = [[], []] as any[][];
  const sessions = frames.map(rows => createCalculationSession(async (_request, quote) =>
    mapQuoteJobs(40, index => quote({ amount: String(index) }), quote.signal), frame => rows.push(frame), () => 'failure'));
  try {
    sessions.forEach((session, index) => session.receive({ id: String(index) }));
    await until(() => frames.every(rows => rows.length === 8));
    assert.equal(frames.flat().length, 16, 'the cap is per driver, not per process or per calculation');
    sessions[0].receive({ id: '0', operation: 'cancel' });
    await setImmediate();
    assert.equal(frames[1].length, 8);
  } finally { sessions.forEach(session => session.close()); await setImmediate(); }
});

test('retirement during an admitted factory cannot emit for its retired owner', { timeout: 5000 }, async () => {
  const frames: any[] = [];
  const session = createCalculationSession(async (request, quote) => {
    await requestQuote(quote, () => {
      session.receive({ id: request.id, operation: 'cancel' });
      return { amount: '100' };
    });
    return [];
  }, frame => { frames.push(frame); }, () => 'failure');
  session.receive({ id: 'cancelled-in-factory' });
  await setImmediate();
  assert.deepEqual(frames, [{ id: 'cancelled-in-factory', operation: 'cancelled' }]);
  session.close();
});
