"""Display-only integer Core/Helpers arithmetic; exact previews remain authoritative."""
PPM, FP = 1_000_000, 10**18


def ceil_div(a, b):
    return (a + b - 1) // b


def gross_for_net(net, fee):
    if net <= 0:
        raise ValueError('positive net required by the existing contract')
    return net + (net - 1) * fee // (PPM - fee)


def wire(value):
    if isinstance(value, dict):
        return {k: v if k == 'kind' else wire(v) for k, v in value.items()}
    if isinstance(value, list):
        return [wire(v) for v in value]
    return str(value) if type(value) is int else value


class BasketArithmetic:
    """Integer translation of Core/Helpers calculation, excluding validation."""
    def __init__(self, state):
        self.s = state
        self.denominator = max(state['supply'], sum(
            ceil_div(a * c, FP) for a, c in zip(state['available'], state['conversions'], strict=True)
        ) + sum(state['recoveryValues']))

    def issue(self, net, *, includes_helper=False):
        s = self.s
        core_net = gross_for_net(net, s['helperFee']) if includes_helper else net
        gross = gross_for_net(core_net, s['issueFee'])
        if gross > min(s['maxSupply'], s['effectiveCap']) - s['supply']:
            raise ValueError('existing supply cap exceeded')
        lots = [ceil_div(ceil_div(gross * w, PPM) * FP, c)
                for w, c in zip(s['weights'], s['conversions'], strict=True)]
        helper_fee = core_net - net if includes_helper else core_net * s['helperFee'] // PPM
        result = {'fees': {'protocolFeeCygld': gross - core_net, 'helperFeeCygld': helper_fee},
                  'amountsInExact': lots, 'orderedCoreAssets': s['assets']}
        if not includes_helper:
            result['netCygldOut'] = core_net - helper_fee
        return result

    def issue_in(self, budgets):
        s = self.s
        gross = min((b * c // FP) * PPM // w for b, c, w in
                    zip(budgets, s['conversions'], s['weights'], strict=True) if w)
        gross = min(gross, max(0, min(s['maxSupply'], s['effectiveCap']) - s['supply']))
        return self.issue(gross - gross * s['issueFee'] // PPM)

    def redeem_in(self, gross):
        s = self.s
        helper_fee = gross * s['helperFee'] // PPM
        core_gross = gross - helper_fee
        if core_gross > s['supply']:
            raise ValueError('existing supply bound exceeded')
        core_fee = core_gross * s['redeemFee'] // PPM
        net = core_gross - core_fee
        amounts = s['available'] + s['recoveryShares']
        outputs = [{**d, 'amount': a * net // self.denominator}
                   for d, a in zip(s['descriptors'], amounts, strict=True)]
        return {'fees': {'protocolFeeCygld': core_fee, 'helperFeeCygld': helper_fee},
                'projectedCoreOutputs': outputs}

    def redeem_out(self, minima):
        s = self.s
        amounts = s['available'] + s['recoveryShares']
        if any(m and (not a or m > a) for m, a in zip(minima, amounts, strict=True)):
            raise ValueError('existing unavailable output bound exceeded')
        net = max((ceil_div(m * self.denominator, a) if m else 0)
                  for m, a in zip(minima, amounts, strict=True))
        gross = gross_for_net(gross_for_net(net, s['redeemFee']), s['helperFee'])
        return {'grossCygldIn': gross, **self.redeem_in(gross)}
