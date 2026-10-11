import json
import sys
from pathlib import Path

from cybergold_candidate.rpc_policy import validate_payload, valid_response_payload

fixtures = json.loads((Path(__file__).parents[1] / 'fixtures/rpc-policy.json').read_text())
results = [{'name': case['name'], 'result': (validate_payload(case['value']) if case['kind'] == 'request'
                                         else valid_response_payload(case['value']))} for case in fixtures]
assert results == json.loads(Path(sys.argv[1]).read_text()), 'Node/Python RPC envelope difference'
print(f'PASS: {len(results)} actual Node/Python RPC policy comparisons; existing methods/batches/error precedence')
