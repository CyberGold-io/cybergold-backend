/** Optional per-exchange timings. No payload, IDs or per-frame log is retained. */
export class WorkerTiming {
  private received: bigint;
  private started = 0n;
  private cpu = process.cpuUsage();
  constructor(received: bigint) { this.received = received; }
  start() {
    this.started = process.hrtime.bigint();
    this.cpu = process.cpuUsage();
  }
  frame(value: unknown) {
    const computed = process.hrtime.bigint(), cpu = process.cpuUsage(this.cpu);
    const encoded = JSON.stringify(value);
    const timing = { receivedNs: String(this.received), startedNs: String(this.started),
      computedNs: String(computed), writeStartedNs: String(process.hrtime.bigint()),
      processCpuUserUs: cpu.user, processCpuSystemUs: cpu.system };
    // The business frame is already encoded. The stamp precedes only this small
    // timing suffix/pipe write, not encoding an arbitrarily large result.
    return encoded.slice(0, -1)+',"_sdkTiming":'+JSON.stringify(timing)+'}\n';
  }
}
