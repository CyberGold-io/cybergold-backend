"""Faucet outcomes retain safe messages, correlation and the existing funding contract."""
import asyncio
import json
import logging
import unittest
from unittest.mock import patch

import httpx

from cybergold_candidate.app import create_app
from cybergold_candidate.faucet import REQUEST_ID


ADDRESS='0x'+'a'*40
REQUEST='11111111-1111-4111-8111-111111111111'
IP='203.0.113.7'
TOKEN='1'*64
URL='http://127.0.0.1:9999/fund'
PRIVATE='fixture-private-provider-body Authorization: Bearer '+TOKEN+' '+URL+' '+ADDRESS+' '+IP
BODY={'address':ADDRESS,'requestId':REQUEST}
SUCCESS={'status':'ok','address':ADDRESS,'ethWei':'1','tokens':[],'dryRun':False}
FORWARDED={'x-real-ip':IP,'x-forwarded-for':IP}


class FaucetErrorDiagnosticsHttp(unittest.IsolatedAsyncioTestCase):
    async def request(self,supplier,*,body=BODY,headers=FORWARDED,settings=None,timeout=20):
        calls=[]
        async def upstream(request):
            calls.append(request)
            return await supplier(request)
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as upstream_client:
            app=create_app(client=upstream_client,faucet_settings={
                'enabled':True,'url':URL,'token':TOKEN,**(settings or {})},faucet_timeout_seconds=timeout)
            async with app.router.lifespan_context(app),httpx.AsyncClient(
                transport=httpx.ASGITransport(app),base_url='http://fixture') as client:
                with self.assertLogs('cybergold.candidate',level='ERROR') as captured:
                    response=await client.post('/api/faucet',json=body,headers=headers)
        payload=response.json()
        self.assertEqual(set(payload),{'error','code','correlationId'})
        self.assertRegex(payload['correlationId'],REQUEST_ID)
        record=json.loads(captured.records[0].getMessage())
        self.assertEqual(len(captured.records),1)
        self.assertEqual(record['correlationId'],payload['correlationId'])
        self.assertEqual(record['errorClassification'],payload['code'])
        self.assertEqual(record['context'],'faucet')
        self.assertGreaterEqual(record['diagnostics']['elapsedMs'],0)
        self.assertEqual(response.headers['cache-control'],'no-store')
        for secret in [PRIVATE,TOKEN,URL,ADDRESS,IP,REQUEST]:
            self.assertNotIn(secret,response.text+json.dumps(record))
        return response,payload,record['diagnostics'],calls

    async def test_known_adapter_outcomes_preserve_status_headers_and_single_submission(self):
        references=set()
        for status,upstream,code,expected_status,replace in [
            (400,'INVALID_ADDRESS','REQUEST_REJECTED',400,None),
            (401,'UNAUTHORIZED','AUTHENTICATION_FAILED',502,None),
            (408,'REQUEST_TIMEOUT','TIMEOUT',504,None),
            (409,'REQUEST_ID_CONFLICT','REQUEST_CONFLICT',409,'replace'),
            (409,'REQUEST_IN_PROGRESS','REQUEST_IN_PROGRESS',409,None),
            (409,'REQUEST_UNCERTAIN','REQUEST_UNCERTAIN',409,'replace'),
            (429,'ADDRESS_QUOTA_EXHAUSTED','ADDRESS_QUOTA_EXHAUSTED',429,None),
            (429,'IP_QUOTA_EXHAUSTED','IP_QUOTA_EXHAUSTED',429,None),
            (429,'GLOBAL_QUOTA_EXHAUSTED','GLOBAL_QUOTA_EXHAUSTED',429,None),
            (500,'INTERNAL_ERROR','BAD_GATEWAY',502,None),
            (502,'FUNDING_FAILED','FUNDING_FAILED',502,'replace'),
            (503,'CHAIN_UNAVAILABLE','CHAIN_UNAVAILABLE',503,None),
        ]:
            with self.subTest(upstream=upstream):
                async def supplier(_request):
                    return httpx.Response(status,json={'error':{'code':upstream,'message':PRIVATE}},
                        headers={'Retry-After':'30'})
                response,payload,diagnostics,calls=await self.request(supplier)
                self.assertEqual(response.status_code,expected_status)
                self.assertEqual(payload['code'],code)
                self.assertEqual(diagnostics['stage'],'faucet-adapter')
                self.assertEqual(diagnostics['failureType'],'http-error')
                self.assertEqual(diagnostics['httpStatus'],status)
                self.assertEqual(diagnostics['upstreamErrorCode'],upstream)
                self.assertEqual(response.headers.get('x-cybergold-faucet-request-id'),replace)
                self.assertEqual(response.headers.get('retry-after'),'30' if status==429 else None)
                self.assertEqual(len(calls),1)
                self.assertEqual(json.loads(calls[0].content),{**BODY,'requesterIp':IP})
                self.assertEqual(calls[0].headers['authorization'],'Bearer '+TOKEN)
                self.assertNotIn(payload['correlationId'],references)
                references.add(payload['correlationId'])
                if upstream=='REQUEST_UNCERTAIN':self.assertIn('could not be confirmed',payload['error'])
                if upstream=='REQUEST_IN_PROGRESS':self.assertIn('still being processed',payload['error'])

    async def test_transport_provider_timeout_and_backend_deadline_are_distinct(self):
        async def refusal(_request):raise httpx.ConnectError(PRIVATE)
        async def provider_timeout(_request):raise httpx.ReadTimeout(PRIVATE)
        async def pending(_request):await asyncio.Event().wait()
        for supplier,code,failure_type,status in [
            (refusal,'BAD_GATEWAY','transport-error',502),
            (provider_timeout,'TIMEOUT','provider-timeout',504),
            (pending,'TIMEOUT','backend-deadline',504),
        ]:
            with self.subTest(failure_type=failure_type):
                response,payload,diagnostics,calls=await self.request(supplier,timeout=.01)
                self.assertEqual(response.status_code,status)
                self.assertEqual(payload['code'],code)
                self.assertEqual(diagnostics['failureType'],failure_type)
                self.assertEqual(diagnostics['stage'],'faucet-adapter')
                self.assertNotIn('httpStatus',diagnostics)
                self.assertNotIn('upstreamErrorCode',diagnostics)
                self.assertNotIn('x-cybergold-faucet-request-id',response.headers)
                self.assertEqual(len(calls),1)

    async def test_invalid_response_never_authenticates_unvalidated_private_details(self):
        for status,body,content_type in [
            (502,PRIVATE,'text/html'),
            (200,'{','application/json'),
            (429,json.dumps({'error':{'code':'INVALID_ADDRESS','message':PRIVATE}}),'application/json'),
            (409,json.dumps({'error':{'code':'REQUEST_UNCERTAIN','message':PRIVATE,'extra':True}}),'application/json'),
        ]:
            with self.subTest(status=status,content_type=content_type):
                async def supplier(_request):
                    return httpx.Response(status,content=body,headers={'content-type':content_type})
                response,payload,diagnostics,calls=await self.request(supplier)
                self.assertEqual(response.status_code,502)
                self.assertEqual(payload['code'],'INVALID_RESPONSE')
                self.assertEqual(diagnostics['failureType'],'invalid-response')
                self.assertEqual(diagnostics['httpStatus'],status)
                self.assertNotIn('upstreamErrorCode',diagnostics)
                self.assertEqual(len(calls),1)

    async def test_rejected_ingress_keeps_existing_validation_without_adapter_call(self):
        async def supplier(_request):raise AssertionError('Rejected request must not fund')
        for body,headers,settings,status,code in [
            ({**BODY,'extra':True},FORWARDED,None,400,'INVALID_REQUEST'),
            (BODY,{},None,400,'INVALID_REQUESTER_IP'),
            (BODY,FORWARDED,{'enabled':False},403,'DISABLED'),
            (BODY,{**FORWARDED,'content-type':'text/plain'},None,415,'UNSUPPORTED_MEDIA_TYPE'),
            ({**BODY,'address':'x'*513},FORWARDED,None,413,'REQUEST_TOO_LARGE'),
            (BODY,FORWARDED,{'token':'invalid'},503,'CONFIGURATION_ERROR'),
        ]:
            with self.subTest(code=code):
                response,payload,diagnostics,calls=await self.request(supplier,body=body,headers=headers,settings=settings)
                self.assertEqual(response.status_code,status)
                self.assertEqual(payload['code'],code)
                self.assertEqual(diagnostics['stage'],'faucet-request')
                self.assertEqual(diagnostics['failureType'],'request-error')
                self.assertEqual(calls,[])

    async def test_logging_outage_does_not_change_the_error_or_funding_result(self):
        count=0
        async def supplier(_request):
            nonlocal count
            count+=1
            return httpx.Response(409,json={'error':{'code':'REQUEST_UNCERTAIN','message':PRIVATE}}) if count==1 \
                else httpx.Response(200,json=SUCCESS)
        async with httpx.AsyncClient(transport=httpx.MockTransport(supplier)) as upstream:
            app=create_app(client=upstream,faucet_settings={'enabled':True,'url':URL,'token':TOKEN})
            async with app.router.lifespan_context(app),httpx.AsyncClient(
                transport=httpx.ASGITransport(app),base_url='http://fixture') as api:
                with patch.object(logging.getLogger('cybergold.candidate'),'error',side_effect=RuntimeError('logger unavailable')):
                    failure=await api.post('/api/faucet',json=BODY,headers=FORWARDED)
                    success=await api.post('/api/faucet',json=BODY,headers=FORWARDED)
                self.assertEqual(failure.status_code,409)
                self.assertEqual(failure.json()['code'],'REQUEST_UNCERTAIN')
                self.assertEqual(failure.headers['x-cybergold-faucet-request-id'],'replace')
                self.assertRegex(failure.json()['correlationId'],REQUEST_ID)
                self.assertEqual(success.status_code,200)
                self.assertEqual(success.json(),SUCCESS)
                self.assertEqual(count,2)


if __name__=='__main__':unittest.main()
