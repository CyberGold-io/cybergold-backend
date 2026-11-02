"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.RouteQuoteAllocator = void 0;
const RouteBasic_1 = require("../../models/route/RouteBasic");
const QuoteSplit_1 = require("../../models/quote/QuoteSplit");
class RouteQuoteAllocator {
    /**
     * Generates all possible partial routes per percentage step.
     * @param routes Array of routes to generate partial routes from
     * @param percentageStep The percentage step to generate partial routes for
     * @returns Array of RouteBasic, where each RouteBasic contains a partial route
     */
    getAllPercentageRoutes(routes, percentageStep) {
        // Generate all possible partial routes per percentage step
        const pctRoutes = [];
        for (const route of routes) {
            for (let pct = 100; pct >= percentageStep; pct -= percentageStep) {
                pctRoutes.push(new RouteBasic_1.RouteBasic(route.protocol, route.path, pct));
            }
        }
        return pctRoutes;
    }
    /**
     * Combines split routes and their quotes back into quote splits.
     * @param splitQuotes Array of quotes for split routes
     * @param routeCombinations Array of route combinations that were used to generate the quotes
     * @param ctx UniContext
     * @returns Array of QuoteSplit, where each QuoteSplit contains the quotes for a route combination
     */
    stitchQuotes(splitQuotes, routeCombinations,
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    ctx) {
        // Group quotes by their route combination
        const quoteSplits = [];
        // Process each route combination
        for (const combination of routeCombinations) {
            // Find all quotes that match this combination's routes
            const matchingQuotes = this.findMatchingQuotes(splitQuotes, combination);
            if (matchingQuotes.length !== combination.length) {
                // Skip if we don't have quotes for all routes in this combination
                // TODO: log
                continue;
            }
            quoteSplits.push(new QuoteSplit_1.QuoteSplit(matchingQuotes));
        }
        return quoteSplits;
    }
    findMatchingQuotes(quotes, routes) {
        return routes
            .map(route => {
            // Find the quote that matches this route
            return quotes.find(quote => this.routesMatch(quote.route, route));
        })
            .filter((quote) => quote !== undefined);
    }
    routesMatch(route1, route2) {
        if (route1.path.length !== route2.path.length) {
            return false;
        }
        // Check if percentages match
        if (route1.percentage !== route2.percentage) {
            return false;
        }
        // Check if all pools match in order by comparing their addresses
        return route1.path.every((pool, index) => pool.address.equals(route2.path[index].address));
    }
}
exports.RouteQuoteAllocator = RouteQuoteAllocator;
//# sourceMappingURL=RouteQuoteAllocator.js.map