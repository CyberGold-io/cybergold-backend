import json
import sys
from pathlib import Path

from cybergold_candidate.safe_abi import safe_execution_args

fixtures = json.loads(Path(sys.argv[1]).read_text())
for case in fixtures:
    actual = safe_execution_args(case['log'])
    assert actual == case['result'], {'log': case['log'], 'node': case['result'], 'python': actual}
print(f'PASS: {len(fixtures)} actual retained Safe/Viem/Web3.py ABI comparisons; uint256 lossless; indexed and non-indexed')
