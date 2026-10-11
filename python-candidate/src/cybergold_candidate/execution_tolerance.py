"""Lossless execution limits around a quoted integer amount."""
DEFAULT_SLIPPAGE_BPS = 100
BPS_DENOMINATOR = 10_000


def floor(amount, slippage_bps=DEFAULT_SLIPPAGE_BPS):
    return max(1, amount * (BPS_DENOMINATOR - slippage_bps) // BPS_DENOMINATOR) if amount else 0


def ceil(amount, slippage_bps=DEFAULT_SLIPPAGE_BPS):
    return (amount * (BPS_DENOMINATOR + slippage_bps) + BPS_DENOMINATOR - 1) // BPS_DENOMINATOR
