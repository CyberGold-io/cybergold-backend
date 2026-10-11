import json
from pathlib import Path
import sys

from cybergold_candidate.environment import EnvironmentBase,SETTINGS


def main(path):
    cases=json.loads(Path(path).read_text())
    for case in cases:
        definition=SETTINGS[case['name']]
        previous=definition['required']
        definition['required']=case['required']
        class Info:field_name=case['name']
        try:
            try:
                result=EnvironmentBase.setting(case['value'],Info())
                error=None
            except ValueError as failure:
                result=None;error=str(failure)
            assert (result,error)==(case['result'],case['error']),case
        finally:
            definition['required']=previous
    print(f'PASS: {len(cases)} actual Node/Pydantic setting comparisons; existing required fields, formats and value-free errors')


if __name__=='__main__':main(sys.argv[1])
