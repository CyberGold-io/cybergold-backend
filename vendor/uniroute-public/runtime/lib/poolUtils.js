"use strict";
// A model-only 1:1 native/wrapped edge; never a physical pool or price oracle.
exports.FAKE_TICK_SPACING = -1;
let wrapped = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2";
exports.configureWrappedCurrency = value => { wrapped = value.toLowerCase(); };
exports.getV4EthWethFakePool = _chainId => ({
  protocol: "v4", tickSpacing: exports.FAKE_TICK_SPACING, nativeTransition: true,
  token0: { lowerCased: "0x0000000000000000000000000000000000000000" },
  token1: { lowerCased: wrapped },
});
