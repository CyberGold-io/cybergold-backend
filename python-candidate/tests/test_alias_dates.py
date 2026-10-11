import json
from pathlib import Path
import math
import sys

from cybergold_candidate.alias_dates import date_milliseconds


def main(path):
    fixture=json.loads(Path(path).read_text());failures=[]
    for case in fixture['values']:
        actual=date_milliseconds(case['text']);expected=case['value']
        if not (math.isnan(actual) if expected is None else actual==expected):failures.append((case['text'],actual,expected))
    assert not failures, (fixture['timezone'],len(failures),failures[:24])
    print(f"PASS: {len(fixture['values'])} actual V8/Python permissive timestamp comparisons in {fixture['timezone']}")


if __name__=='__main__':main(sys.argv[1])
