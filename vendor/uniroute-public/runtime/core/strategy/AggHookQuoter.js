"use strict";
// Preserve all supplied paths on the canonical callback arm. This wiring does
// not drop hooks or claim to implement an external hook.quote() execution arm.
exports.partitionAggHookRoutes = routes => ({ aggHookRoutes: [], otherRoutes: routes });
exports.fetchAggHookQuotes = async () => { throw new Error('Remote hook quotes are unavailable in canonical nomination'); };
