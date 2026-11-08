"use strict";
// Do not add Uniswap's unavailable private token/blocking policy to CyberGold.
exports.RoutingBlockList = { dropPoolsThroughBlockedRoutingTokens: pools => pools };
