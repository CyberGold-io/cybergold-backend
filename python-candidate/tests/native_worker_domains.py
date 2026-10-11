"""Run completion/fork comparisons in the actual local Linux candidate image."""
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).parents[2]
CODE='''
import asyncio,json,sys,tempfile
from pathlib import Path
sys.path.insert(0,'/fixture')
import test_completed_state,test_fork_recovery,test_fork_control
fixture=json.load(sys.stdin)
async def run():
    with tempfile.TemporaryDirectory() as directory:
        path=Path(directory)/'completion.json';path.write_text(json.dumps(fixture['completion']))
        await test_completed_state.main(path)
    await test_fork_recovery.check(fixture['fork'])
    await test_fork_control.check(fixture['control'])
asyncio.run(run())
'''
if __name__=='__main__':
    fixture=dict(zip(['completion','fork','control'],[json.loads(Path(path).read_text()) for path in sys.argv[1:]],strict=True))
    image='cybergold-python-candidate:market-parity'
    result=subprocess.check_output(['docker','run','--rm','--interactive',
        '--mount','type=bind,source='+str(ROOT/'python-candidate/tests')+',target=/fixture,readonly',
        '--mount','type=bind,source='+str(ROOT/'src/server/onchain-indexer/snapshot-identity.json')+',target=/app/src/server/onchain-indexer/snapshot-identity.json,readonly',
        '--workdir','/app','--entrypoint','python',image,'-c',CODE],input=json.dumps(fixture),text=True)
    assert result.count('PASS:')==3,result
    identifier=subprocess.check_output(['docker','image','inspect',image,'--format','{{.Id}}'],text=True).strip()
    print(json.dumps({'result':'pass','nativeCompletedStateComparisons':len(fixture['completion']['cases']),
        'nativeCommitBindings':len(fixture['completion']['commits']),
        'nativeReceiptConstruction':len(fixture['completion']['builds']),
        'nativeForkRecoveryComparisons':len(fixture['fork']['cases']),
        'nativeForkControlComparisons':len(fixture['control']),
        'testedImageId':identifier,'installedEndpointsOrDatabaseUsed':False}))
