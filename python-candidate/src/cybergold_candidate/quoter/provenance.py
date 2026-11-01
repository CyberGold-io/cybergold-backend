"""Diagnostic nomination origin; never part of route admission or ranking."""


def origin_names(value):
    # Selected/historical plans do not need this optional metadata to replay.
    if not isinstance(value, (list, tuple)):
        return []
    return sorted({name for name in value if isinstance(name, str)})


def attach_origins(quote):
    conversions = {}
    for operation, chosen in quote.get('plan', {}).get('conversions', {}).items():
        if isinstance(chosen, dict) and chosen.get('branches'):
            # Old selected plans remain usable without origin metadata. Do not
            # invent a supplier when replaying such a historical observation.
            conversions[operation] = origin_names(chosen.get('discoveryOrigins')) or ['unspecified']
    quote['routeOrigins'] = {'economicEvaluator': 'cybergold-quoter',
        'pricing': 'canonical-sdk-and-core-previews',
        'discoveryProviders': sorted({name for names in conversions.values() for name in names})
                              if conversions else ['cybergold-custom'],
        'conversions': conversions}
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
