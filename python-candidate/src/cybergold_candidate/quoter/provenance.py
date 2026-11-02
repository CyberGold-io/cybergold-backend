"""Diagnostic nomination origin; never part of route admission or ranking."""


def origin_names(value):
    # Selected/historical plans do not need this optional metadata to replay.
    if not isinstance(value, (list, tuple)):
        return []
    return sorted({name for name in value if isinstance(name, str)})


def attach_origins(quote):
    conversions, adapter_conversions = {}, []
    for operation, chosen in quote.get('plan', {}).get('conversions', {}).items():
        if isinstance(chosen, dict) and chosen.get('branches'):
            if chosen.get('topologyOrigin') == 'cybergold-adapter':
                # This zero-residual binding composes already selected pool
                # references. It is not a fresh AMM-tool nomination.
                adapter_conversions.append(operation)
                continue
            # Old selected plans remain usable without origin metadata. Do not
            # invent a supplier when replaying such a historical observation.
            conversions[operation] = origin_names(chosen.get('discoveryOrigins')) or ['unspecified']
    quote['routeOrigins'] = {'economicEvaluator': 'cybergold-quoter',
        'pricing': ('helpers-execution-with-policy-fees' if quote.get('pricingEvidence', {}).get('engine') == 'helpers-execution'
                    else 'canonical-sdk-and-core-previews'),
        'discoveryProviders': sorted({name for names in conversions.values() for name in names})
                              if conversions else [],
        'conversions': conversions,
        **({'adapterConversions': sorted(adapter_conversions)} if adapter_conversions else {})}
    return quote


def merge_origins(incumbent, candidate):
    """Record later equivalent nominations without replacing an economic tie."""
    if (incumbent is None or incumbent.get('inputs') != candidate.get('inputs')
            or incumbent.get('quotedOutput') != candidate.get('quotedOutput')):
        return
    left, right = incumbent['plan'], candidate['plan']
    if left['allocations'] != right['allocations'] or left['body'] != right['body']:
        return
    for operation, chosen in left['conversions'].items():
        offered = right['conversions'].get(operation)
        if isinstance(chosen, dict) and isinstance(offered, dict) and chosen.get('template') == offered.get('template'):
            names = set(origin_names(chosen.get('discoveryOrigins')))
            names.update(origin_names(offered.get('discoveryOrigins')))
            if names:
                chosen['discoveryOrigins'] = sorted(names)
    attach_origins(incumbent)
