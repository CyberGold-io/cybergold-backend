"use strict";
// Runtime metrics are not connected; chain identity remains the caller's value.
exports.ChainId = {};
exports.buildMetricKey = value => value;
exports.OPTIMISM_STACK_CHAINS = [];
exports.TAG_STATUS_FAILURE = 'status:failure';
// The caller supplies the existing owner clock, with no private serving default.
exports.getRouteSplitTimeoutMs = (config, chainId) => {
  const cap = config.RouteSplitTimeoutMsCapByChain?.[chainId];
  return cap === undefined ? config.RouteSplitTimeoutMs : Math.min(config.RouteSplitTimeoutMs, cap);
};
