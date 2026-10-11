"""First-party market pricing, separate from Core and AMM fees."""
M = 1_000_000


def get_market_fee_rate(chain_id, token_in, token_out, amount_mode):
    """One replaceable local policy hook; no token lookup or RPC."""
    return 1_000


def div_ceil(numerator, denominator):
    return (numerator + denominator - 1) // denominator


def quoted_fee(notional, rate):
    return div_ceil(notional * rate, M)


def gross_buy_target(net, rate):
    gross = div_ceil(net * M, M - rate)
    return gross, gross - net


def routed_sell_budget(budget, rate):
    routed = budget * M // (M + rate)
    fee = quoted_fee(routed, rate)
    return routed, fee, budget - routed - fee
