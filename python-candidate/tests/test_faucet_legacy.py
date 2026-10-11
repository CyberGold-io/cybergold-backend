import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile

from cybergold_candidate.faucet import Faucet,FaucetError


async def run(path):
    reference=json.loads(Path(path).read_text())
    with tempfile.TemporaryDirectory(prefix='cybergold-legacy-faucet-') as root:
        script=Path(root)/'fund.py';script.write_text(reference['source'])
        for case in reference['cases']:
            mode=case['mode'];script.chmod(0o600 if mode=='not-executable' else 0o700)
            service=Faucet(None,enabled=True,script_path=str(Path(root)/'missing' if mode=='missing' else script),
                foundry_bin='/fixture-foundry',environment={**os.environ,'FIXTURE_LEGACY_MODE':mode,
                    'NODE_ENV':'production' if mode=='production' else 'test'})
            result=None;error=None
            try:result=await service.fund('0x'+'a'*40,None,None)
            except FaucetError as failure:error={'code':failure.code,'status':failure.status,'message':str(failure)}
            assert (result,error)==(case['result'],case['error']),(case,result,error)
        script.write_text('#!'+sys.executable+'\nimport time\ntime.sleep(1)\n');script.chmod(0o700)
        service=Faucet(None,enabled=True,script_path=str(script),timeout_seconds=.05)
        try:await service.fund('0x'+'a'*40,None,None)
        except FaucetError as failure:assert failure.status==504
        else:raise AssertionError('Legacy subprocess deadline did not apply')
    print(f'PASS: {len(reference["cases"])} actual Node/Python legacy faucet subprocess comparisons; deadline terminates the child; no live faucet used')


asyncio.run(run(sys.argv[1]))
