"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.DeepQuoteStrategy = void 0;
const BaseQuoteStrategy_1 = require("./BaseQuoteStrategy");
const Protocol_1 = require("../../models/pool/Protocol");
const config_1 = require("../../lib/config");
const OnChainQuoteFetchError_1 = require("../../stores/quote/OnChainQuoteFetchError");
const TradeType_1 = require("../../models/quote/TradeType");
const helpers_1 = require("../../lib/helpers");
const envParsing_1 = require("../../lib/envParsing");
const RouteBasic_1 = require("../../models/route/RouteBasic");
const QuoteBasic_1 = require("../../models/quote/QuoteBasic");
const QuoteBestSplitFinder_1 = require("../quote/QuoteBestSplitFinder");
const eventLoopSlicer_1 = require("../../lib/eventLoopSlicer");
const AggHookQuoter_1 = require("./AggHookQuoter");
const observability_1 = require("../../lib/observability");
/**
 * DeepQuoteStrategy implements an optimized quote finding logic:
 *
 * 1. ROUTE PCT GENERATION
 * ------------------
 * Generate all possible partial routes per percentage step
 * but only for individual routes (no splits yet).
 *
 * 2. QUOTE FETCHING
 * ----------------
 * Fetch quotes for all individual routes/percentages
 * This gives us a baseline of how each route performs
 * at different percentage allocations
 *
 * 3. QUOTE ORGANIZATION
 * -------------------
 * Group and sort quotes by percentage
 * This lets us quickly access the best performing routes
 * for any given percentage allocation
 *
 * 4. BEST SPLIT FINDING
 * --------------------
 * Use QuoteBestSplitFinder to efficiently find the best
 * route combinations, prioritizing:
 * - Best performing routes
 * - Simpler splits before complex ones
 * - Limited search space per percentage
 * - Respect maximum execution time
 */
class DeepQuoteStrategy extends BaseQuoteStrategy_1.BaseQuoteStrategy {
    quoteBestSplitFinder;
    rpcProviderMap;
    constructor(quoteFetcher, gasEstimateProvider, gasConverter, routeQuoteAllocator, quoteSelector, tokenHandler, arbitrumGasDataProviders, freshPoolDetailsWrapper, rpcProviderMap, splitSearchYieldSliceMs = eventLoopSlicer_1.DEFAULT_EVENT_LOOP_SLICE_MS) {
        super(quoteFetcher, gasEstimateProvider, gasConverter, routeQuoteAllocator, quoteSelector, tokenHandler, arbitrumGasDataProviders, freshPoolDetailsWrapper);
        // Kill-switch for the lowest-gas anchor in the K-budget partition
        // gate. See `QuoteBestSplitFinder.AGG_HOOK_PARTITION_USE_LOWEST_GAS_ANCHOR`
        // for the rationale; default off until the canary deploy validates
        // the change against prod `PartitionAnchorAnalysis` telemetry.
        const useLowestGasAnchor = process.env.AGG_HOOK_PARTITION_USE_LOWEST_GAS_ANCHOR === 'true';
        // Reserved env-flag handle for the projected gas-adjusted gate
        // in the K-budget partition. CURRENTLY A NO-OP FOR ENFORCEMENT
        // — Codex adversarial-review round-5 finding #1 showed that
        // hard-pruning agg-hook on a local projection is unsafe given
        // the DFS conflict-propagation semantics. The wiring stays so a
        // future PR can flip this on once a conflict-aware enforcement
        // implementation lands. Telemetry
        // (`KBudgetAdmitProjectedLoss{verdict:admit_raw_only}`) is
        // computed independently under the `testAggHooks` canary gate.
        const useProjectedGasAdjGate = process.env.AGG_HOOK_PARTITION_USE_PROJECTED_GAS_ADJ_GATE === 'true';
        // Bounded result growth in findBestSplits — caps the synchronous
        // score/sort chunks whale trades balloon between DFS timeout checks
        // (the FindBestSplits overrun). Pure performance flag; selection output
        // is unchanged. See QuoteBestSplitFinder.SPLIT_FINDER_BOUNDED_GROWTH_ENABLED.
        const boundedGrowthEnabled = process.env.SPLIT_FINDER_BOUNDED_GROWTH_ENABLED === 'true';
        // Shadow-budget checkpoint for the split search (dark at 0): when > 0,
        // findBestSplits snapshots its would-be winner at the first level
        // boundary past this elapsed time and emits the quality delta vs the
        // final winner (QuoteBestSplitFinder.ShadowCheckpoint). Metric-only;
        // selection output is unchanged at any value.
        const shadowCheckpointMs = (0, envParsing_1.parsePositiveIntEnvOrDefault)('SPLIT_FINDER_SHADOW_CHECKPOINT_MS', 0);
        this.quoteBestSplitFinder = new QuoteBestSplitFinder_1.QuoteBestSplitFinder(0n, 0n, 0n, useLowestGasAnchor, useProjectedGasAdjGate, 0n, boundedGrowthEnabled, shadowCheckpointMs, splitSearchYieldSliceMs);
        this.rpcProviderMap = rpcProviderMap ?? new Map();
    }
    async findBestQuoteCandidates(ctx, chain, tokenInCurrencyInfo, tokenOutCurrencyInfo, amount, tradeType, protocols, serviceConfig, routes, tokensInfo, metricTags, blockNumber, testAggHooks, supplementalHookCodeOverrides) {
        // Generate all possible partial routes per percentage step
        const pctRoutes = [];
        for (const route of routes) {
            for (let pct = 100; pct >= serviceConfig.RouteFinder.RouteSplitPercentage; pct -= serviceConfig.RouteFinder.RouteSplitPercentage) {
                pctRoutes.push(new RouteBasic_1.RouteBasic(route.protocol, route.path, pct));
            }
        }
        // Partition: single-hop aggregator hook routes are quoted via hook.quote()
        // directly, bypassing the V4Quoter which fails for these pools.
        const { aggHookRoutes, otherRoutes } = (0, AggHookQuoter_1.partitionAggHookRoutes)(pctRoutes);
        const fetchQuotesStartTime = Date.now();
        ctx.logger.debug('Starting fetchQuotes', {
            totalPctRoutes: pctRoutes.length,
            aggHookRoutes: aggHookRoutes.length,
            otherRoutes: otherRoutes.length,
        });
        const safeLogElapsedTime = (title, startTime) => {
            try {
                void (0, helpers_1.logElapsedTime)(title, startTime, ctx, metricTags).catch(() => { });
            }
            catch {
                // Instrumentation must not affect quote execution.
            }
        };
        const recordArmLatency = (promise, title, shouldEmit, startTime) => {
            if (!shouldEmit)
                return promise;
            return promise.then(result => {
                safeLogElapsedTime(title, startTime);
                return result;
            }, error => {
                safeLogElapsedTime(title, startTime);
                throw error;
            });
        };
        // Fetch quotes in parallel: hook.quote() for agg hooks, standard quoter for the rest
        const aggHookQuotesStartTime = Date.now();
        const aggHookFetchReport = {
            droppedRoutes: 0,
            batchErrors: [],
        };
        const aggHookQuotesPromise = aggHookRoutes.length > 0
            ? (0, AggHookQuoter_1.fetchAggHookQuotes)(chain, aggHookRoutes, amount, tradeType, tokenInCurrencyInfo, this.rpcProviderMap, ctx, metricTags, { report: aggHookFetchReport })
            : Promise.resolve([]);
        const standardQuotesStartTime = Date.now();
        const standardFetchReport = {
            droppedRoutes: 0,
            batchErrors: [],
        };
        const standardQuotesPromise = otherRoutes.length > 0
            ? this.quoteFetcher.fetchQuotes(chain, tokenInCurrencyInfo, tokenOutCurrencyInfo, amount, otherRoutes, tradeType, ctx, metricTags, blockNumber, tokensInfo, supplementalHookCodeOverrides, standardFetchReport)
            : Promise.resolve([]);
        const [aggHookQuotes, standardQuotes] = await Promise.all([
            recordArmLatency(aggHookQuotesPromise, 'FetchQuotes.AggHook', aggHookRoutes.length > 0, aggHookQuotesStartTime),
            recordArmLatency(standardQuotesPromise, 'FetchQuotes.Standard', otherRoutes.length > 0, standardQuotesStartTime),
        ]);
        const quotes = [...aggHookQuotes, ...standardQuotes];
        // A pair routed only through an agg hook has no standard arm, so the
        // search is judged on what both arms dropped.
        const fetchReport = {
            droppedRoutes: standardFetchReport.droppedRoutes + aggHookFetchReport.droppedRoutes,
            batchErrors: [
                ...standardFetchReport.batchErrors,
                ...aggHookFetchReport.batchErrors,
            ],
        };
        await (0, helpers_1.logElapsedTime)('FetchQuotes', fetchQuotesStartTime, ctx, metricTags);
        // Update quotes with gas estimation details
        const gasEstimateStartTime = Date.now();
        ctx.logger.debug('Starting gasEstimate');
        const gasPriceWei = serviceConfig.GasEstimation.Enabled
            ? await this.gasEstimateProvider.getCurrentGasPrice(ctx, chain.chainId, blockNumber)
            : 0;
        // Below information is only needed when dealing with Arbitrum Orbit or
        // Optimism Stack chains in order to calculate L2 gas costs accurately. We
        // need to update the quotes with fresh pool details so that we can
        // generate the correct calldata for L2 gas estimation.
        const orbitGasDataProvider = this.arbitrumGasDataProviders.get(chain.chainId);
        let arbitrumGasData = undefined;
        if (orbitGasDataProvider &&
            serviceConfig.L1L2GasCostFetcher.ArbitrumEnabled) {
            arbitrumGasData = await orbitGasDataProvider.getGasData(ctx);
        }
        if ((orbitGasDataProvider &&
            serviceConfig.L1L2GasCostFetcher.ArbitrumEnabled &&
            !serviceConfig.L1L2GasCostFetcher
                .SkipArbitrumCallDataGenerationAndApproximate) ||
            (config_1.OPTIMISM_STACK_CHAINS.includes(chain.chainId) &&
                serviceConfig.L1L2GasCostFetcher.OpStackEnabled)) {
            tokensInfo = await this.updateQuotesWithFreshPoolDetails(quotes, tokensInfo, chain, ctx, metricTags, blockNumber);
        }
        const quotesWithGas = await Promise.all(quotes.map(async (quote) => {
            const gasDetails = await this.gasEstimateProvider.estimateGas(serviceConfig, tokenInCurrencyInfo, tokenOutCurrencyInfo, amount, chain.chainId, tokensInfo, tradeType, quote, ctx, gasPriceWei, arbitrumGasData);
            return new QuoteBasic_1.QuoteBasic(quote.route, quote.amount, quote.v3QuoterResponseDetails, gasDetails);
        }));
        await (0, helpers_1.logElapsedTime)('GasEstimate', gasEstimateStartTime, ctx, metricTags);
        // Populate gasCostInQuoteToken on each quote BEFORE the split-finder
        // ranks combinations. `QuoteBestSplitFinder.scoreAndSortCombinations`
        // ranks combinations by gas-adjusted total amount when this is
        // populated, and falls back to raw amount when it isn't. Prior to
        // this call ordering, the gas conversion happened only post-split in
        // `UniRouteBL`, leaving `findBestSplits` ranking by raw amount alone
        // and producing the residual gas-bad split losses captured by
        // PR #8285 (`agghook_chosen_higher_gas` verdict in prod).
        if (serviceConfig.GasEstimation.Enabled) {
            const startGasConvTime = Date.now();
            await this.gasConverter.updateQuoteBasicsGasDetails(chain.chainId, tradeType === TradeType_1.TradeType.ExactIn
                ? tokenOutCurrencyInfo.wrappedAddress.toString()
                : tokenInCurrencyInfo.wrappedAddress.toString(), tokensInfo, quotesWithGas, ctx, blockNumber);
            await (0, helpers_1.logElapsedTime)('UpdateQuoteBasicsGasDetailsPreSplit', startGasConvTime, ctx, metricTags);
        }
        // Generate a mapping of percentage to sorted quotes. Dedup quotes by
        // their canonical route string within each percentage bucket: diagnostic
        // logs on WBTC->USDT 10 BTC showed the top no-hook 1-hop route landed
        // in the same percentage bucket twice, wasting a slot in the K=2
        // per-percentage budget downstream. Route-layer dedupe in
        // BaseRoutesRepository catches dupes among the 100%-percentage routes;
        // this catches anything that slips through later stages (e.g. quote
        // retries, partition spill).
        const percentageToSortedQuotes = new Map();
        const seenByPercentage = new Map();
        let quoteDuplicatesRemoved = 0;
        for (const quote of quotesWithGas) {
            const percentage = quote.route.percentage;
            const key = quote.route.toString();
            let seen = seenByPercentage.get(percentage);
            if (!seen) {
                seen = new Set();
                seenByPercentage.set(percentage, seen);
            }
            if (seen.has(key)) {
                quoteDuplicatesRemoved++;
                continue;
            }
            seen.add(key);
            if (!percentageToSortedQuotes.has(percentage)) {
                percentageToSortedQuotes.set(percentage, []);
            }
            percentageToSortedQuotes.get(percentage)?.push(quote);
        }
        if (quoteDuplicatesRemoved > 0) {
            ctx.logger.debug('DeepQuoteStrategy deduped duplicate quotes', {
                chainId: chain.chainId,
                beforeDedup: quotesWithGas.length,
                afterDedup: quotesWithGas.length - quoteDuplicatesRemoved,
                duplicatesRemoved: quoteDuplicatesRemoved,
            });
        }
        // Sort quotes by amount - descending for EXACT_IN, ascending for EXACT_OUT
        for (const percentage of percentageToSortedQuotes.keys()) {
            const quotes = percentageToSortedQuotes.get(percentage);
            quotes.sort((a, b) => {
                const comparison = b.amount > a.amount ? 1 : b.amount < a.amount ? -1 : 0;
                return tradeType === TradeType_1.TradeType.ExactOut ? -comparison : comparison;
            });
        }
        const percentageBucketSummary = Array.from(percentageToSortedQuotes.entries()).map(([percentage, quotes]) => ({
            percentage,
            quoteCount: quotes.length,
            aggHookQuoteCount: quotes.filter(quote => quote.route.path.some(pool => (0, observability_1.isAggHookPool)(pool, chain.chainId))).length,
            v3OnlyQuoteCount: quotes.filter(quote => quote.route.path.every(pool => pool.protocol === Protocol_1.Protocol.V3)).length,
        }));
        const aggHookQuoteCountTotal = percentageBucketSummary.reduce((sum, bucket) => sum + bucket.aggHookQuoteCount, 0);
        const v3OnlyQuoteCountTotal = percentageBucketSummary.reduce((sum, bucket) => sum + bucket.v3OnlyQuoteCount, 0);
        ctx.logger.debug('DeepQuoteStrategy percentage bucket observability', {
            chainId: chain.chainId,
            tradeType,
            protocols: protocols.join(',').toLowerCase(),
            routeSplitPercentage: serviceConfig.RouteFinder.RouteSplitPercentage,
            pctRoutes: pctRoutes.length,
            quotesWithGas: quotesWithGas.length,
            percentageBuckets: percentageBucketSummary,
        });
        const deepQuoteStrategyMetricTags = [
            ...metricTags,
            `testAggHooks:${testAggHooks}`,
        ];
        // Bucket-level distribution metrics. The route-cap fix (PR #8301)
        // gave no-hook routes the full MaxRoutes budget but didn't move the
        // residual UniRoute-wins-by-gas-adjusted rate on prod. Top losing
        // hash `ab69b143` is `winnerMismatchRawVsGasAdjusted:false` —
        // treatment is worse than control on BOTH raw AND gas-adjusted, yet
        // uniroute still picks it. That implies the gas-adj-better route
        // control finds isn't in treatment's candidate set — i.e., the
        // divergence happens upstream of `findBestSplits` (pool discovery /
        // route enumeration / quote fetch / cached-routes hit-miss differ
        // between testAggHooks=true and testAggHooks=false runs).
        //
        // These metrics expose per-percentage bucket counts as queryable
        // distributions so we can diff treatment vs control on the same
        // chain/tradeType: if `avg:NoHookQuotesAtPercentage.dist{...
        // testagghooks:true}` is smaller than the testagghooks:false
        // counterpart at any percentage, the route enumeration / quote
        // fetch is dropping no-hook quotes specifically when agg-hooks are
        // enabled. Per-percentage tag has 20 distinct values (5..100 in 5%
        // steps); combined with chain (~20) / tradeType (2) /
        // testagghooks (2-3) the dimension cardinality is bounded
        // (~2400 combinations) and well within DD's tag-cardinality budget.
        const noHookQuoteCountTotal = percentageBucketSummary.reduce((sum, bucket) => sum + (bucket.quoteCount - bucket.aggHookQuoteCount), 0);
        const percentageBucketDistEmissions = percentageBucketSummary.flatMap(bucket => {
            const perBucketTags = [
                ...deepQuoteStrategyMetricTags,
                `percentage:${bucket.percentage}`,
            ];
            return [
                ctx.metrics.dist((0, config_1.buildMetricKey)('DeepQuoteStrategy.NoHookQuotesAtPercentage.dist'), bucket.quoteCount - bucket.aggHookQuoteCount, { tags: perBucketTags }),
                ctx.metrics.dist((0, config_1.buildMetricKey)('DeepQuoteStrategy.AggHookQuotesAtPercentage.dist'), bucket.aggHookQuoteCount, { tags: perBucketTags }),
            ];
        });
        await Promise.all([
            ctx.metrics.count((0, config_1.buildMetricKey)('DeepQuoteStrategy.PctRoutes'), pctRoutes.length, { tags: deepQuoteStrategyMetricTags }),
            ctx.metrics.count((0, config_1.buildMetricKey)('DeepQuoteStrategy.AggHookQuotes'), aggHookQuoteCountTotal, { tags: deepQuoteStrategyMetricTags }),
            ctx.metrics.count((0, config_1.buildMetricKey)('DeepQuoteStrategy.V3OnlyQuotes'), v3OnlyQuoteCountTotal, { tags: deepQuoteStrategyMetricTags }),
            // Per-request total no-hook / agg-hook counts as distributions —
            // gives avg/max/min/p95 across calls without per-percentage tag
            // cardinality. The cleanest single signal for "is treatment's
            // overall no-hook universe smaller than control's?".
            ctx.metrics.dist((0, config_1.buildMetricKey)('DeepQuoteStrategy.NoHookQuoteCountTotal.dist'), noHookQuoteCountTotal, { tags: deepQuoteStrategyMetricTags }),
            ctx.metrics.dist((0, config_1.buildMetricKey)('DeepQuoteStrategy.AggHookQuoteCountTotal.dist'), aggHookQuoteCountTotal, { tags: deepQuoteStrategyMetricTags }),
            ctx.metrics.dist((0, config_1.buildMetricKey)('DeepQuoteStrategy.PercentageBucketCount.dist'), percentageBucketSummary.length, { tags: deepQuoteStrategyMetricTags }),
            ...percentageBucketDistEmissions,
        ]);
        // Use QuoteBestSplitFinder to find optimal route combinations
        const findSplitsStartTime = Date.now();
        const routeSplitTimeoutMs = (0, config_1.getRouteSplitTimeoutMs)(serviceConfig.RouteFinder, chain.chainId);
        ctx.logger.debug('Starting findBestSplits');
        const splitRoutes = await this.quoteBestSplitFinder.findBestSplits(chain.chainId, percentageToSortedQuotes, serviceConfig.RouteFinder.RouteSplitPercentage, serviceConfig.RouteFinder.MaxSplits, serviceConfig.RouteFinder.MaxSplitRoutes, routeSplitTimeoutMs, tradeType, metricTags, ctx, testAggHooks);
        const findBestSplitsLatencyMs = Date.now() - findSplitsStartTime;
        await (0, helpers_1.logElapsedTime)('FindBestSplits', findSplitsStartTime, ctx, metricTags);
        ctx.logger.debug('DeepQuoteStrategy split search observability', {
            chainId: chain.chainId,
            tradeType,
            protocols: protocols.join(',').toLowerCase(),
            findBestSplitsLatencyMs,
            routeSplitTimeoutMs,
            maxSplits: serviceConfig.RouteFinder.MaxSplits,
            maxSplitRoutes: serviceConfig.RouteFinder.MaxSplitRoutes,
            splitRoutes: splitRoutes.length,
        });
        ctx.logger.debug(`--> Routes (${routes.length})`);
        ctx.logger.debug(`--> PctRoutes (${pctRoutes.length})`);
        ctx.logger.debug(`--> QuotesWithGas (${quotesWithGas.length})`);
        ctx.logger.debug(`--> SplitRoutes (${splitRoutes.length})`);
        await ctx.metrics.count((0, config_1.buildMetricKey)('SplitRoutes'), splitRoutes.length, {
            tags: metricTags,
        });
        await ctx.metrics.count((0, config_1.buildMetricKey)('Routes'), routes.length, {
            tags: metricTags,
        });
        await ctx.metrics.count((0, config_1.buildMetricKey)('PctRoutes'), pctRoutes.length, {
            tags: metricTags,
        });
        // Reconstruct QuoteSplit[] from QuoteBasic[] by stitching together the split routes
        ctx.logger.debug('Starting stitchQuotes');
        const stitchedQuotesWithGas = this.routeQuoteAllocator.stitchQuotes(quotesWithGas, splitRoutes, ctx);
        // The dropped routes may hold the only viable split, so an empty result
        // here is not evidence that no route exists. The search ends with an
        // `incomplete` error instead of an empty candidate list, which
        // UniRouteBL serves as no route without writing the no-route cache.
        if (stitchedQuotesWithGas.length === 0 && fetchReport.droppedRoutes > 0) {
            await ctx.metrics.count((0, config_1.buildMetricKey)('DeepQuoteStrategy.IncompleteFetch'), 1, {
                tags: [...metricTags, config_1.TAG_STATUS_FAILURE, 'reason:dropped_routes'],
            });
            ctx.logger.debug('Quote fetch dropped routes and no split could be built, ending the search as incomplete', {
                chainId: chain.chainId,
                droppedRoutes: fetchReport.droppedRoutes,
                quotedRoutes: quotes.length,
                pctRoutes: pctRoutes.length,
            });
            throw new OnChainQuoteFetchError_1.OnChainQuoteFetchError('incomplete', fetchReport.batchErrors);
        }
        return stitchedQuotesWithGas;
    }
    /**
     * Updates quotes with fresh pool details needed for L2 gas estimation.
     * Only needed for Arbitrum/Optimism Stack chains.
     * @param quotes - Quotes to update (mutated in place)
     * @param tokensInfo - Map of token info
     * @param chain - Chain information
     * @param ctx - Context
     * @param metricTags - Metric tags for logging
     * @returns Updated tokensInfo map
     */
    async updateQuotesWithFreshPoolDetails(quotes, tokensInfo, chain, ctx, metricTags, blockNumber) {
        // Ensure we have fresh pool details for all pools involved in the quotes as we need it to generate calldata for L2 gas estimation
        // Only needed for Arbitrum/Optimism Stack chains
        tokensInfo = await (0, helpers_1.fetchAllInvolvedTokens)(quotes, this.tokenHandler, chain, ctx, tokensInfo);
        const poolsToUpdate = quotes.map(quote => quote.route.path).flat();
        const poolsCount = poolsToUpdate.length;
        const freshPoolDetailsStartTime = Date.now();
        ctx.logger.debug('Starting FreshPoolDetailsUpdateForGasEstimation update', {
            poolsCount,
        });
        const updatedPoolsMap = await this.freshPoolDetailsWrapper.getPoolsDetails(ctx, poolsToUpdate, chain, blockNumber);
        await (0, helpers_1.updateQuotesWithFreshPoolDetailsUsingPoolsMap)(updatedPoolsMap, quotes, ctx);
        await (0, helpers_1.logElapsedTime)('FreshPoolDetailsUpdateForGasEstimation', freshPoolDetailsStartTime, ctx, metricTags);
        ctx.logger.debug('Completed FreshPoolDetailsUpdateForGasEstimation', {
            elapsedTime: Date.now() - freshPoolDetailsStartTime,
            poolsCount,
            updatedPoolsCount: updatedPoolsMap.size,
        });
        return tokensInfo;
    }
    name() {
        return 'DeepQuoteStrategy';
    }
}
exports.DeepQuoteStrategy = DeepQuoteStrategy;
//# sourceMappingURL=DeepQuoteStrategy.js.map