"""Compare completed results within one request; estimates never enter here."""


def prefer_completed(candidate, incumbent, *, scalar):
    if incumbent is None:
        return True
    output, previous = int(candidate['quotedOutput']), int(incumbent['quotedOutput'])
    if output != previous:
        return output > previous
    if not scalar:
        return False
    # These are the producer's declared acquisitions, not the budget minus a
    # guessed retention. Never order basket vectors/different currencies by
    # summing their incomparable raw units.
    inputs, old_inputs = candidate['inputs'], incumbent['inputs']
    if len(inputs) != 1 or len(old_inputs) != 1:
        return False
    if inputs[0]['currency'].lower() != old_inputs[0]['currency'].lower():
        return False
    return int(inputs[0]['amount']) < int(old_inputs[0]['amount'])
