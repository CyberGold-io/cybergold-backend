import json
from pathlib import Path
import sys

from cybergold_candidate.core_activity import decode_core_activity

fixtures = json.loads(Path(sys.argv[1]).read_text())
for case in fixtures:
    observed = decode_core_activity(case['row'])
    assert observed == case['result'], {'node': case['result'], 'python': observed}
print(f'PASS: {len(fixtures)} actual Core/Viem/Web3.py event comparisons; historical migrations, tuples, wide integers, unknown logs')
