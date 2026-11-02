"use strict";
exports.logElapsedTime = async () => {};
// Nomination uses zero gas and never constructs remote L2 execution calldata.
exports.fetchAllInvolvedTokens = async () => { throw new Error('L2 gas is unavailable in canonical nomination'); };
exports.updateQuotesWithFreshPoolDetailsUsingPoolsMap = exports.fetchAllInvolvedTokens;
