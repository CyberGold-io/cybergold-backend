"use strict";
exports.WRAPPED_NATIVE_CURRENCY = {};
exports.configureWrappedCurrency = (chainId, address) => {
  exports.WRAPPED_NATIVE_CURRENCY[chainId] = { address };
};
