"use strict";
const { createHash } = require('node:crypto');
// Every supplied pool goes through the canonical quote callback. No external
// aggregator-hook price arm or private hook classification is introduced.
exports.isAggHookPool = () => false;
exports.routeUsesAggHook = () => false;
exports.hashForLogging = value => createHash('sha256').update(value).digest('hex').slice(0, 8);
