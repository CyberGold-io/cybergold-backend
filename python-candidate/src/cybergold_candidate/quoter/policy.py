"""Conservative optional Market bounds; estimates never become quote amounts."""
from fractions import Fraction

from ..market_fee import M, get_market_fee_rate, routed_sell_budget
from ..routing_encoding import ZERO
from ..uniswap_routes import pool_identity


def output_upper_bound(registry, request, route, block):
    """Independent acyclic base-state paths only; unknown means price normally.

    Constant-product and fixed-fee concentrated-liquidity swaps cannot improve
    their own marginal input/output price along one direction. Their starting
    fee-adjusted spot product bounds output before impact and integer loss.
    This says nothing about Core, interacting operations, or undiscovered paths.
    """
    try:
        observe = getattr(registry, 'observation', None)
        if observe is None or request['intent'] not in (0, 1):
            return None
        source, target = request['inputs'][0]['currency'], request['outputCurrency']
        amount = int(request['inputs'][0]['amount'])
        rate = get_market_fee_rate(registry.chain, source, target, 'exact-in')
        if request['intent'] == 1:
            amount -= routed_sell_budget(amount, rate)[1]
        value, seen = Fraction(amount), set()
        for hop in route:
            if 'pool' not in hop:
                if hop.get('kind') not in ('wrap', 'unwrap'):
                    return None
                continue
            pool = hop['pool']
            identity = pool_identity(pool)
            if identity in seen or (pool.get('hooks') or ZERO).lower() != ZERO:
                return None
            seen.add(identity)
            state = observe(pool)
            if state is None or state.get('context', {}).get('blockHash', '').lower() != block['hash'].lower():
                return None
            direction = hop['zeroForOne']
            fee = int(state['feePips'])
            if state['protocol'] == 'v2':
                a, b = (int(state['reserve0']), int(state['reserve1'])) if direction else (
                    int(state['reserve1']), int(state['reserve0']))
                if a <= 0 or b <= 0:
                    return None
                price = Fraction(b, a)
            elif state['protocol'] in ('v3', 'v4'):
                sqrt = int(state['sqrtRatioX96'])
                if sqrt <= 0:
                    return None
                price = Fraction(sqrt * sqrt, 2**192) if direction else Fraction(2**192, sqrt * sqrt)
                if state['protocol'] == 'v4':
                    packed = int(state['protocolFee'])
                    protocol = (packed & 0xfff) if direction else (packed >> 12) & 0xfff
                    lp = int(state['lpFee'])
                    fee = protocol + lp - protocol * lp // M
            else:
                return None
            if not 0 <= fee < M:
                return None
            value *= price * Fraction(M - fee, M)
        if request['intent'] == 0:
            value *= Fraction(M - rate, M)
        return (value.numerator + value.denominator - 1) // value.denominator
    except (KeyError, TypeError, ValueError, ZeroDivisionError, AttributeError):
        return None


def dominated(bound, incumbent):
    # Equal output can still win by declared funding. Never prune a tie.
    return bound is not None and incumbent is not None and bound < int(incumbent['quotedOutput'])
