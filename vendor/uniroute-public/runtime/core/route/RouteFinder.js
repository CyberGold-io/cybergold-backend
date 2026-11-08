"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.RouteFinder = void 0;
const RouteBasic_1 = require("../../models/route/RouteBasic");
const config_1 = require("../../lib/config");
const poolUtils_1 = require("../../lib/poolUtils");
const config_2 = require("../../lib/config");
const Protocol_1 = require("../../models/pool/Protocol");
const CanonicalPools_1 = require("../../lib/CanonicalPools");
const RoutingBlockList_1 = require("../../lib/RoutingBlockList");
const METRIC_NON_CANONICAL_POOL = (0, config_1.buildMetricKey)('RouteFinder.NonCanonicalPool');
const METRIC_BLOCKED_ROUTING_TOKEN_POOL = (0, config_1.buildMetricKey)('RouteFinder.BlockedRoutingTokenPool');
class RouteFinder {
    serviceConfig;
    constructor(serviceConfig) {
        this.serviceConfig = serviceConfig;
    }
    // TODO: https://linear.app/uniswap/issue/ROUTE-410/ (modify for V4 - Support ETH+WETH pools)
    async generateRoutes(chainId, candidatePools, tokenIn, tokenOut, allowMixedPools, ctx) {
        const routes = [];
        // Every non-cached route is built here, from whatever pool sources the
        // repositories assembled (selector output, cache hits, cross-liquidity
        // and registry appends, on-chain probes), so this is where the
        // canonical-pools rule and the every-hop routing block list are
        // enforced for correctness. Upstream filters only save slots and probes.
        // Copied so the fake ETH/WETH push below never mutates the caller's
        // array.
        const pools = [
            ...CanonicalPools_1.CanonicalPools.dropNonCanonicalPools(RoutingBlockList_1.RoutingBlockList.dropPoolsThroughBlockedRoutingTokens(candidatePools, chainId, CanonicalPools_1.identifyPoolModel, ctx, METRIC_BLOCKED_ROUTING_TOKEN_POOL), chainId, CanonicalPools_1.identifyPoolModel, ctx, METRIC_NON_CANONICAL_POOL),
        ];
        // If mixed pools are allowed and we have V4 pools, add a fake pool for ETH/WETH to allow connectivity.
        if (allowMixedPools && pools.some(pool => pool.protocol === Protocol_1.Protocol.V4)) {
            const fakePool = (0, poolUtils_1.getV4EthWethFakePool)(chainId);
            if (fakePool) {
                pools.push(fakePool);
            }
        }
        const findAllPathsStartTime = Date.now();
        // First pass: find routes with standard MaxHops
        this.findAllPaths(pools, tokenIn, tokenOut, [], new Set(), routes, allowMixedPools, false // useExtendedHops = false
        );
        const normalRoutesCount = routes.length;
        // Extended search: if we found fewer routes than threshold or all routes are 1-hop only (direct pair), consider more hops
        const { MinRoutesThreshold, MaxHopsExtended, MaxExtendedRoutes, MaxHops } = this.serviceConfig.RouteFinder;
        const allRoutesAreSingleHop = routes.length > 0 && routes.every(route => route.path.length === 1);
        let extendedRoutesCount = 0;
        let extendedSearchTriggered = false;
        if ((routes.length < MinRoutesThreshold || allRoutesAreSingleHop) &&
            MaxHopsExtended > MaxHops &&
            MaxExtendedRoutes > 0) {
            extendedSearchTriggered = true;
            const extendedRoutes = [];
            this.findAllPaths(pools, tokenIn, tokenOut, [], new Set(), extendedRoutes, allowMixedPools, true // useExtendedHops = true
            );
            // Filter to only include routes with more hops than MaxHops (avoid duplicates)
            // and cap at MaxExtendedRoutes
            const newRoutes = extendedRoutes
                .filter(route => route.path.length > MaxHops)
                .slice(0, MaxExtendedRoutes);
            extendedRoutesCount = newRoutes.length;
            routes.push(...newRoutes);
        }
        // Emit metrics if context is available
        if (ctx) {
            const metricTags = [`chain:${config_2.ChainId[chainId]}`];
            const findAllPathsElapsed = Date.now() - findAllPathsStartTime;
            ctx.logger.debug(`[Latency] RouteFinder.findAllPaths took ${findAllPathsElapsed}ms`);
            await ctx.metrics.dist((0, config_1.buildMetricKey)('RouteFinder.findAllPaths.Latency.dist'), findAllPathsElapsed, { tags: metricTags });
            await ctx.metrics.count((0, config_1.buildMetricKey)('RouteFinder.NormalRoutesCount'), normalRoutesCount, { tags: metricTags });
            await ctx.metrics.count((0, config_1.buildMetricKey)('RouteFinder.ExtendedSearchTriggered'), extendedSearchTriggered ? 1 : 0, { tags: metricTags });
            if (extendedSearchTriggered) {
                await ctx.metrics.count((0, config_1.buildMetricKey)('RouteFinder.ExtendedRoutesCount'), extendedRoutesCount, { tags: metricTags });
            }
        }
        return routes;
    }
    findAllPaths(pools, currentToken, tokenOut, currentPath, visitedTokens, routes, allowMixedPools, useExtendedHops) {
        // Special case for routes that contain the fake eth/weth pool, add an extra hop
        const currentRouteContainsFakeV4Pool = currentPath.some(pool => pool.protocol === Protocol_1.Protocol.V4 &&
            pool.tickSpacing === poolUtils_1.FAKE_TICK_SPACING);
        const baseMaxHops = useExtendedHops
            ? this.serviceConfig.RouteFinder.MaxHopsExtended
            : this.serviceConfig.RouteFinder.MaxHops;
        const maxHops = currentRouteContainsFakeV4Pool
            ? baseMaxHops + 1
            : baseMaxHops;
        // Stop if we've exceeded max hops
        if (currentPath.length >= maxHops) {
            return;
        }
        // Mark current token as visited to prevent cycles
        visitedTokens.add(currentToken.lowerCased);
        // Find all pools that have currentToken as one of their tokens
        const validPools = pools.filter(pool => {
            const hasToken = (pool.token0.lowerCased === currentToken.lowerCased ||
                pool.token1.lowerCased === currentToken.lowerCased) &&
                !currentPath.includes(pool);
            // If not allowing mixed pools and we have a current path,
            // check if the pool's protocol matches the protocol of the first pool in the path
            if (!allowMixedPools && currentPath.length > 0) {
                return hasToken && pool.protocol === currentPath[0].protocol;
            }
            return hasToken;
        });
        for (const pool of validPools) {
            // Determine the other token in the pool
            const otherToken = pool.token0.lowerCased === currentToken.lowerCased
                ? pool.token1
                : pool.token0;
            // Skip if we've already visited this token
            if (visitedTokens.has(otherToken.lowerCased)) {
                continue;
            }
            // Add this pool to our current path
            currentPath.push(pool);
            // If we've found the target token, create a new route
            if (otherToken.lowerCased === tokenOut.lowerCased) {
                // Create a copy of the current path
                const pathCopy = [...currentPath];
                // Check if we have mixed protocols in the path
                const protocols = new Set(pathCopy.map(pool => pool.protocol));
                const protocol = protocols.size > 1 ? Protocol_1.Protocol.MIXED : pool.protocol;
                routes.push(new RouteBasic_1.RouteBasic(protocol, pathCopy));
            }
            else {
                // Otherwise, continue searching from this new token
                this.findAllPaths(pools, otherToken, tokenOut, currentPath, visitedTokens, routes, allowMixedPools, useExtendedHops);
            }
            // Backtrack
            currentPath.pop();
        }
        // Remove the current token from visited set when backtracking
        visitedTokens.delete(currentToken.lowerCased);
    }
}
exports.RouteFinder = RouteFinder;
//# sourceMappingURL=RouteFinder.js.map