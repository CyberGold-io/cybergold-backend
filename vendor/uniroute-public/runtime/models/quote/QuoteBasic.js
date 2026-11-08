"use strict";
exports.QuoteBasic = class QuoteBasic {
  constructor(route, amount, v3QuoterResponseDetails, gasDetails) {
    Object.assign(this, { route, amount, v3QuoterResponseDetails, gasDetails });
  }
};
