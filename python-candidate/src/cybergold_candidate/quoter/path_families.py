"""Economic path families, derived from funded semantic Core operations.

A Core-containing scalar split belongs to the Core family even when another
branch is a pure market operation. Discovery-provider and presentation labels
never decide the family.
"""
PATH_FAMILIES = ('market', 'core')


def quote_path_family(quote):
    if quote.get('request', {}).get('intent', 0) >= 2:
        return 'core'
    branches = quote.get('plan', {}).get('body', {}).get('branches', [])
    return 'core' if any(branch['kind'] == 0 and int(branch['amountIn']) > 0
                         for branch in branches) else 'market'
