"use strict";
exports.OnChainQuoteFetchError = class OnChainQuoteFetchError extends Error {
  constructor(reason, errors) { super(reason); this.reason = reason; this.errors = errors; }
};
