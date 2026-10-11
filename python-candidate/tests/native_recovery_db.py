"""Bidirectional retained Node/Python projection writes in disposable PostgreSQL."""
import asyncio
import json
import os
import subprocess

from cybergold_candidate.recovery_persistence import reconcile_v2, read_checkpoint


async def qualify_recovery(pool,dsn,root):
    core='0x0000000000000000000000000000000000000003'
    first='0x0000000000000000000000000000000000000001'
    second='0x0000000000000000000000000000000000000002'
    zero='0x'+'0'*40
    hashes={letter:'0x'+letter*64 for letter in 'abcdef'}
    supply=2**200

    async def insert(block,from_address,to,amount):
        async with pool.connection() as connection:
            await connection.execute('''INSERT INTO onchain_event_logs(chain_id,contract_address,
                event_name,block_number,tx_hash,log_index,block_timestamp,payload)
                VALUES(31338,%s,'TransferSingle',%s,%s,0,'2026-09-30T10:00:00Z',%s::jsonb)''',
                (core,block,'recovery-'+str(block),json.dumps({'args':{
                    'operator':first,'from':from_address,'to':to,'id':'1','value':str(amount)}})))

    async def project(block,letter,profile='fixture-profile',canonical=None):
        async with pool.connection() as connection:
            async with connection.transaction():
                return await reconcile_v2(connection,31338,core,block,hashes[letter],profile,canonical)

    async def view():
        async with pool.connection() as connection:
            checkpoint=await read_checkpoint(connection,31338,core)
            checkpoint={**checkpoint,'blockNumber':str(checkpoint['blockNumber'])}
            balances=await (await connection.execute('''SELECT share_id,holder_address,balance_raw
                FROM onchain_recovery_share_balances_v2 WHERE chain_id=31338 AND contract_address=%s
                ORDER BY holder_address,share_id::numeric''',(core,))).fetchall()
            return {'checkpoint':checkpoint,'balances':balances}

    async def node(apply=False):
        return json.loads(await asyncio.to_thread(subprocess.check_output,
            ['node','--env-file=tests/fixture.env','--import','tsx',
             'python-candidate/tests/node-recovery-db-reference.ts'],cwd=root,
            env={**os.environ,'DATABASE_URL':dsn,'FIXTURE_APPLY':'1' if apply else '0'},text=True))

    await insert(100,zero,first,supply)
    assert await project(100,'a')=={'rebuilt':True,'appliedLogCount':1}
    python=await view();retained=await node()
    assert python=={key:retained[key] for key in ('checkpoint','balances')}
    assert python['balances'][0]['balance_raw']==str(supply)
    await insert(101,first,second,7)
    assert await project(101,'b',canonical=hashes['a'])=={'rebuilt':False,'appliedLogCount':1}
    await insert(102,second,zero,2)
    retained=await node(True)
    assert retained['result']=={'rebuilt':False,'appliedLogCount':1}
    assert await view()=={key:retained[key] for key in ('checkpoint','balances')}
    assert await project(102,'c')=={'rebuilt':False,'appliedLogCount':0}
    assert [row['balance_raw'] for row in retained['balances']]==[str(supply-7),'5']
    assert await project(103,'d','changed-profile',hashes['c'])=={'rebuilt':True,'appliedLogCount':3}
    async with pool.connection() as connection:
        await connection.execute('''UPDATE onchain_event_logs SET
            payload=jsonb_set(payload,'{args,value}','"9"') WHERE chain_id=31338
            AND contract_address=%s AND block_number=101''',(core,))
    assert await project(104,'e','changed-profile',hashes['a'])=={'rebuilt':True,'appliedLogCount':3}
    before=await view()
    assert [row['balance_raw'] for row in before['balances']]==[str(supply-9),'7']
    await insert(105,second,zero,100)
    try:await project(105,'f','changed-profile',hashes['e'])
    except ValueError as failure:assert str(failure)=='ERC-1155 recovery-share replay underflow'
    else:raise AssertionError('Invalid retained transfer did not fail')
    assert await view()==before
    retained=await node()
    assert before=={key:retained[key] for key in ('checkpoint','balances')}
    return {'recoveryV2NodePythonBidirectionalWrites':True,'recoveryV2IncrementalAndNoop':True,
        'recoveryV2ProfileAndCanonicalRebuild':True,'recoveryV2FailedReplayAtomic':True}
