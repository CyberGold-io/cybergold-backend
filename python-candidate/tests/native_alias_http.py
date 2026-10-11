"""Signed candidate HTTP writes against the fresh retained-schema DB fixture."""
import asyncio
import json
import os
import subprocess


async def qualify(api,database,dsn,root):
    code='''import {privateKeyToAccount} from 'viem/accounts';
      import {parseSignature,signatureToCompactSignature,serializeCompactSignature} from 'viem';
      import {buildGovernanceOwnerAliasAuthMessage} from './src/utils/governanceOwnerAliasesAuth.ts';
      const account=privateKeyToAccount('0x'+'1'.repeat(64));const result=[];
      for(const action of ['upsert','delete']){
        const params={action,editorAddress:account.address,ownerAddress:'0x'+'a'.repeat(40),
          alias:action==='upsert'?'Native signed HTTP 😀':'',nonce:'native-http-'+action,issuedAt:new Date().toUTCString()};
        const signature=await account.signMessage({message:buildGovernanceOwnerAliasAuthMessage(params)});
        result.push({...params,auth:{nonce:params.nonce,issuedAt:params.issuedAt,signature}});
      }
      const params={action:'upsert',editorAddress:account.address,ownerAddress:'0x'+'b'.repeat(40),
        alias:'Compact ISO HTTP 😀',nonce:'native-http-compact',issuedAt:new Date().toISOString()};
      const signature=await account.signMessage({message:buildGovernanceOwnerAliasAuthMessage(params)});
      const compact=serializeCompactSignature(signatureToCompactSignature(parseSignature(signature)));
      result.push({...params,auth:{nonce:params.nonce,issuedAt:params.issuedAt,signature:compact},standard:signature});
      console.log(JSON.stringify(result));'''
    payloads=json.loads(await asyncio.to_thread(subprocess.check_output,
        ['node','--import','tsx','--input-type=module','-e',code],cwd=root,text=True))
    payload=payloads[0]
    saved=await api.post('/api/governance/owner-aliases',json=payload)
    assert saved.status_code==200 and saved.json()['entry']['alias']=='Native signed HTTP 😀'
    assert saved.headers['Cache-Control']=='no-store'
    replay=await api.post('/api/governance/owner-aliases',json=payload)
    assert replay.status_code==401 and replay.json()['error']=='Alias authorization nonce has already been used.'
    wrong={**payload,'alias':'tampered','auth':{**payload['auth'],'nonce':'unused-tampered'}}
    rejected=await api.post('/api/governance/owner-aliases',json=wrong)
    assert rejected.status_code==401
    code='''import {listOwnerAliases} from './src/server/governance-owner-aliases/repository.ts';
      console.log(JSON.stringify(await listOwnerAliases({editorAddress:process.env.FIXTURE_EDITOR,
        ownerAddresses:[process.env.FIXTURE_OWNER]})));
      await globalThis.__cybergoldDashboardPgPool?.end();'''
    node=json.loads(await asyncio.to_thread(subprocess.check_output,
        ['node','--env-file=tests/fixture.env','--import','tsx','--input-type=module','-e',code],cwd=root,
        env={**os.environ,'DATABASE_URL':dsn,'FIXTURE_EDITOR':payload['editorAddress'],'FIXTURE_OWNER':payload['ownerAddress']},text=True))
    assert node==[saved.json()['entry']]
    deleted=await api.post('/api/governance/owner-aliases',json=payloads[1])
    assert deleted.status_code==200 and deleted.json()=={'ok':True,'deleted':True}
    listed=await api.post('/api/governance/owner-aliases',json={'action':'list',
        'editorAddress':payload['editorAddress'],'ownerAddresses':[payload['ownerAddress']]})
    assert listed.status_code==200 and listed.json()=={'entries':[]}
    compact={key:value for key,value in payloads[2].items() if key!='standard'}
    compact_saved=await api.post('/api/governance/owner-aliases',json=compact)
    assert compact_saved.status_code==200 and compact_saved.json()['entry']['alias']=='Compact ISO HTTP 😀'
    compact_replay=await api.post('/api/governance/owner-aliases',json={**compact,'auth':{**compact['auth'],'signature':payloads[2]['standard']}})
    assert compact_replay.status_code==401 and compact_replay.json()['error']=='Alias authorization nonce has already been used.'
    async with database.connection() as connection:
        rows=await (await connection.execute("SELECT nonce FROM governance_owner_alias_auth_nonces WHERE nonce LIKE 'native-http-%' ORDER BY nonce")).fetchall()
        assert [row['nonce'] for row in rows]==['native-http-compact','native-http-delete','native-http-upsert']
        assert await (await connection.execute("SELECT nonce FROM governance_owner_alias_auth_nonces WHERE nonce='unused-tampered'")).fetchone() is None
    return {'runtimeSignedAliasHttp':True,'rfcTimestampAndSignatureAuthorized':True,
            'signedHttpNonceReplayRejected':True,'retainedNodeReadsHttpAliasWrite':True,
            'signedHttpDeletePreservesConsumedNonces':True,'nativeCompactIsoHttpAndCrossEncodingReplay':True}
