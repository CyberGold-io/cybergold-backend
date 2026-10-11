"""Retained deterministic range subdivision; transport decides approved errors."""


def valid_range(value):
    if value['fromBlock'] < 0 or value['fromBlock'] > value['toBlock']:
        raise ValueError('Adaptive log range is invalid')


def split_range(value):
    valid_range(value)
    start, end = value['fromBlock'], value['toBlock']
    if start == end:
        raise ValueError('A one-block log range cannot be split')
    middle = (start+end)//2
    return [{'fromBlock':start,'toBlock':middle},{'fromBlock':middle+1,'toBlock':end}]


def exact_coverage(base, ranges):
    valid_range(base)
    expected = base['fromBlock']
    for value in ranges:
        valid_range(value)
        if value['fromBlock'] != expected or value['toBlock'] > base['toBlock']:
            raise ValueError('Adaptive log ranges do not exactly cover the base range')
        expected = value['toBlock']+1
    if expected != base['toBlock']+1:
        raise ValueError('Adaptive log ranges do not exactly cover the base range')


async def execute_ranges(baseRange, requestRange, validateRange, shouldSplitRequestFailure=None,
                         maxAttempts=128, maxRanges=128, maxCardinality=50_000):
    valid_range(baseRange)
    for name,value in (('attempt',maxAttempts),('range',maxRanges),('cardinality',maxCardinality)):
        if type(value) is not int or not 0 < value <= 2**53-1:
            raise ValueError(f'Adaptive log {name} cap must be a positive safe integer')
    pending, successful, values = [baseRange], [], []
    attempts, adaptive_attempts, created_ranges = 0, 0, 1
    while pending:
        if attempts >= maxAttempts:
            raise ValueError('Adaptive log request attempt cap was exceeded')
        value = pending.pop()
        adaptive = value != baseRange
        attempts += 1
        adaptive_attempts += int(adaptive)
        try:
            response = await requestRange({'range':value,'adaptive':adaptive})
        except Exception as failure:
            if shouldSplitRequestFailure is None or not shouldSplitRequestFailure(failure):
                raise ValueError('Address-scoped log request failed without an approved range-reduction signal') from None
            if value['fromBlock'] == value['toBlock']:
                raise ValueError('Address-scoped log request failed for one block') from None
            if created_ranges+2 > maxRanges:
                raise ValueError('Adaptive log request range cap was exceeded') from None
            left, right = split_range(value)
            created_ranges += 2
            pending.extend((right,left))
            continue
        range_values = await validateRange(response,value)
        if len(values)+len(range_values) > maxCardinality:
            raise ValueError('Adaptive log response cardinality cap was exceeded')
        successful.append(value)
        values.extend(range_values)
    exact_coverage(baseRange,successful)
    return {'values':values,'successfulRanges':successful,'attemptCount':attempts,
            'adaptiveAttemptCount':adaptive_attempts}
