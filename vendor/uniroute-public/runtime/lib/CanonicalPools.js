"use strict";
// The unavailable private policy is not reproduced. Our configured producer
// and canonical replay retain their existing responsibilities.
exports.identifyPoolModel = pool => pool;
exports.CanonicalPools = { dropNonCanonicalPools: pools => pools };
