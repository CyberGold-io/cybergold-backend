"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.BaseQuoteStrategy = void 0;
class BaseQuoteStrategy {
    quoteFetcher;
    gasEstimateProvider;
    gasConverter;
    routeQuoteAllocator;
    quoteSelector;
    tokenHandler;
    arbitrumGasDataProviders;
    freshPoolDetailsWrapper;
    constructor(quoteFetcher, gasEstimateProvider, gasConverter, routeQuoteAllocator, quoteSelector, tokenHandler,
    // Keyed by chainId so each Arbitrum Orbit chain uses its own RPC for the
    // L1 fee precompile read. Arbitrum One + Robinhood today; extend as needed.
    arbitrumGasDataProviders, freshPoolDetailsWrapper) {
        this.quoteFetcher = quoteFetcher;
        this.gasEstimateProvider = gasEstimateProvider;
        this.gasConverter = gasConverter;
        this.routeQuoteAllocator = routeQuoteAllocator;
        this.quoteSelector = quoteSelector;
        this.tokenHandler = tokenHandler;
        this.arbitrumGasDataProviders = arbitrumGasDataProviders;
        this.freshPoolDetailsWrapper = freshPoolDetailsWrapper;
    }
}
exports.BaseQuoteStrategy = BaseQuoteStrategy;
//# sourceMappingURL=BaseQuoteStrategy.js.map