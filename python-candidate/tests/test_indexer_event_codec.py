import json
import sys
from cybergold_candidate.dashboard_builder import DEFINITIONS
from cybergold_candidate.indexer_event_codec import decode_known, decode_legacy


def check(cases):
    for case in cases:
        known = error = None
        try:
            known = decode_known(case['log'], case['domain'])
        except Exception as failure:
            error = str(failure)
        definition = next(entry for entry in DEFINITIONS[case['domain']] if entry['name'] == case['name'])
        actual = {'known': known, 'error': error, 'legacy': decode_legacy(case['log'], definition)}
        assert actual == case['expected'], (case['name'], case['mode'], actual, case['expected'])
    print(f'PASS: {len(cases)} actual retained Core/Governance strict raw and permissive legacy event decodings')


if __name__ == '__main__':
    check(json.load(open(sys.argv[1])))
