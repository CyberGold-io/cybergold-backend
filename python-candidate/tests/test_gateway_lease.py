"""Actual retained-client comparison; no installed broker is used."""
import asyncio
import json
from pathlib import Path
import sys

import httpx

from cybergold_candidate.gateway_lease import (GatewayClient, GatewayRangeReductionError, accounting_failure,
    assert_runtime, from_environment, health_suppressed, range_reduction_required, restart_required)
from cybergold_candidate.reconciliation_receipt import GatewayMethodRejectedError, RpcCounter

URL='http://broker.test/rpc/indexer'
TOKEN='a'*43
ACQUIRED={'kind':'cybergold-rpc-indexer-lease','formatVersion':1,'reconciliationId':'fixture:1',
    'configRevision':'c'*64,'expiresInSeconds':60,'finalizedAnchor':{'number':100,'hash':'0x'+'b'*64},'leaseToken':'d'*43}
EXPECTED={'reconciliationId':'fixture:1','expectedRuntimeRevision':'c'*64,
    'expectedFinalizedAnchor':{'blockNumber':100,'blockHash':'0x'+'b'*64}}


class DifferentUrlResponse(httpx.Response):
    @property
    def url(self):return httpx.URL('http://different.test/rpc/indexer')


async def compare(case):
    spec=case['specification'];calls=[];now=spec.get('issuedNow',1000);lease=None
    counter=RpcCounter()
    async def handler(request):
        body=json.loads(request.content);headers=request.headers
        calls.append({'path':request.url.path,'body':{**body,**({'id':0} if 'method' in body else {})},
            'authorization':headers.get('authorization')=='Bearer '+TOKEN,'lease':headers.get('x-cybergold-rpc-lease'),
            'reconciliation':headers.get('x-cybergold-rpc-reconciliation'),'redirect':'error'})
        reply=spec['reply'] if spec['operation']=='acquire' or request.url.path.endswith('/release') or 'method' in body else {'body':ACQUIRED}
        if reply.get('throws'):raise RuntimeError('synthetic transport failure')
        raw=reply.get('raw',json.dumps(reply.get('body'),ensure_ascii=False,separators=(',',':')))
        status=reply.get('status',200)
        response=(DifferentUrlResponse if reply.get('otherUrl') else httpx.Response)(status,content='' if status in (204,205,304) else raw,
            headers={'content-type':reply.get('contentType','application/json'),
                **({'content-length':reply['length'].strip(' \t')} if 'length' in reply else {})},request=request)
        return response
    result=error=None
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        try:
            gateway=GatewayClient(URL,TOKEN,client,lambda:now)
            expected=spec.get('expectation',EXPECTED)
            expected={**expected,'expectedFinalizedAnchor':{**expected['expectedFinalizedAnchor'],
                'blockNumber':int(expected['expectedFinalizedAnchor']['blockNumber'])}}
            lease=await gateway.acquire(expected)
            if spec['operation']=='acquire':result={'reconciliationId':lease.reconciliation_id,
                'finalizedAnchor':{**lease.finalized_anchor,'blockNumber':str(lease.finalized_anchor['blockNumber'])},
                'configRevision':lease.config_revision,'expiresInSeconds':lease.expires_in_seconds,'expiresAtMs':lease.expires_at_ms}
            elif spec['operation']=='release':await lease.release();result=True
            else:
                if spec['operation']=='after-release':await lease.release()
                now=spec.get('requestNow',now)
                async def before():
                    nonlocal now
                    if spec.get('beforeExpires'):now=61000
                    if spec.get('beforeThrows'):raise RuntimeError('synthetic callback failure')
                    if spec.get('beforeFailure')=='range':raise GatewayRangeReductionError()
                    if spec.get('beforeFailure')=='accounting':raise GatewayMethodRejectedError()
                result=await lease.request(spec.get('method','eth_chainId'),[],counter,
                    before if spec.get('beforeExpires') or spec.get('beforeThrows') or spec.get('beforeFailure') else None)
        except Exception as failure:
            error={'restart':restart_required(failure) if lease else False,
                'range':range_reduction_required(failure) if lease else False,
                'accounting':accounting_failure(failure) if lease else False}
            if spec['operation'] in ('acquire','release'):error['message']=str(failure)
    assert (result,error,calls,counter.snapshot())==(case['result'],case['error'],case['calls'],case['counts']),{
        'specification':spec,'actual':(result,error,calls,counter.snapshot()),'expected':case}


async def main(path):
    fixture=json.loads(Path(path).read_text())
    for case in fixture['cases']:await compare(case)
    async with httpx.AsyncClient() as client:
        for case in fixture['environments']:
            result=error=None
            try:result=from_environment(case['value'],client) is not None
            except ValueError as failure:error=str(failure)
            assert (result,error)==(case['result'],case['error']),case
    for case in fixture['health']:
        value=case['input'];assert health_suppressed(value['activeReconciliationId'],value['ambiguousUntilMs'],value['nowMs'])==case['result'],case
    for case in fixture['runtime']:
        value=case['input'];error=None
        try:assert_runtime(value['enabled'],int(value['chainId']),value['archiveFreeFinalizedMode'],value['addressScopedRawLogs'])
        except ValueError as failure:error=str(failure)
        assert error==case['error'],case
    print(f"PASS: {len(fixture['cases'])} actual Node/Python lease acquire/release/RPC comparisons, "
        f"{len(fixture['environments'])} environment, {len(fixture['health'])} health and {len(fixture['runtime'])} retained runtime-policy cases")


if __name__=='__main__':asyncio.run(main(sys.argv[1]))
