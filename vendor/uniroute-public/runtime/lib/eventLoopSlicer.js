"use strict";
exports.DEFAULT_EVENT_LOOP_SLICE_MS = 5;
// The adapter uses the fixed positive slice above; no runtime eligibility check.
exports.assertValidSliceMs = () => {};
// Cooperative yield only: no selection deadline, retry or admission allowance.
exports.EventLoopSlicer = class EventLoopSlicer {
  constructor(sliceMs) { this.sliceMs = sliceMs; this.started = performance.now(); }
  async yieldIfSliceElapsed() {
    if (performance.now()-this.started >= this.sliceMs) {
      await new Promise(resolve => setImmediate(resolve));
      this.started = performance.now();
    }
  }
};
