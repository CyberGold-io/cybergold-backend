"""Compare completed results within one request; estimates never enter here."""


def lower_funding(candidate, incumbent):
    """Compare like currencies componentwise, never by summing raw units."""
    inputs, previous = candidate['inputs'], incumbent['inputs']
    if len(inputs) != len(previous) or any(a['currency'].lower() != b['currency'].lower()
            for a, b in zip(inputs, previous, strict=True)):
        return False
    amounts = [(int(a['amount']), int(b['amount'])) for a, b in zip(inputs, previous, strict=True)]
    return all(a <= b for a, b in amounts) and any(a < b for a, b in amounts)


def prefer_completed(candidate, incumbent, *, scalar, basket=False):
    if incumbent is None:
        return True
    if basket:
        outputs, previous = candidate['estimatedRecipientOutputs'], incumbent['estimatedRecipientOutputs']
        if len(outputs) != len(previous) or any(
                (a['kind'], a['token'].lower(), a['id']) != (b['kind'], b['token'].lower(), b['id'])
                for a, b in zip(outputs, previous, strict=True)):
            return False
        amounts = [(int(a['amount']), int(b['amount'])) for a, b in zip(outputs, previous, strict=True)]
        if any(a < b for a, b in amounts):
            return False
        return any(a > b for a, b in amounts) or lower_funding(candidate, incumbent)
    output, previous = int(candidate['quotedOutput']), int(incumbent['quotedOutput'])
    if output != previous:
        return output > previous
    if not scalar:
        return False
    # These are the producer's declared acquisitions, not the budget minus a
    # guessed retention. Never order basket vectors/different currencies by
    # summing their incomparable raw units.
    return len(candidate['inputs']) == 1 and len(incumbent['inputs']) == 1 and lower_funding(candidate, incumbent)
