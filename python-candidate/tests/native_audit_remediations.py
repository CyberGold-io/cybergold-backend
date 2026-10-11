"""Atomic holder and signed alias retries on a disposable PostgreSQL fixture."""
import asyncio
from datetime import datetime, timezone
import os
import subprocess
import time
import unittest
import uuid

import httpx
import psycopg
from psycopg import sql
from eth_account import Account
from eth_account.messages import encode_defunct

from cybergold_candidate.aliases import AliasService, alias_message
from cybergold_candidate.app import create_app
from cybergold_candidate.database import Database
from cybergold_candidate.event_projection import EventProjection
from cybergold_candidate.holder_projection import HolderProjection

CORE,A,B,ZERO=('0x'+char*40 for char in ('3','1','2','0'))
DOCKER=os.environ.get('AUDIT_DOCKER','docker')


class AtomicRetries(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.container='cybergold-audit-regression-'+uuid.uuid4().hex[:12]
        subprocess.run([DOCKER,'run','-d','--name',cls.container,'--publish','127.0.0.1::5432',
            '-e','POSTGRES_PASSWORD=public-audit-fixture','postgres:18-bookworm'],check=True,stdout=subprocess.DEVNULL)
        cls.addClassCleanup(lambda:subprocess.run([DOCKER,'rm','--force','--volumes',cls.container],
            check=True,stdout=subprocess.DEVNULL))
        port=subprocess.check_output([DOCKER,'port',cls.container,'5432/tcp'],text=True).strip().rsplit(':',1)[1]
        cls.url='postgresql://postgres:public-audit-fixture@127.0.0.1:'+port+'/postgres'
        deadline=time.monotonic()+30
        while True:
            try:
                with psycopg.connect(cls.url):break
            except psycopg.OperationalError:
                if time.monotonic()>deadline:raise
                time.sleep(.1)

    async def asyncSetUp(self):
        name='audit_'+uuid.uuid4().hex[:12]
        with psycopg.connect(self.url,autocommit=True) as connection:
            connection.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
        self.url_fixture=self.url.rsplit('/',1)[0]+'/'+name
        self.database=Database(self.url_fixture)
        self.addAsyncCleanup(self.database.close)
        await self.database.ensure_schema()
        self.config={'chainId':1,'coreAddress':CORE}
        self.holder=HolderProjection(self.database,self.config)
        self.projection=EventProjection(self.database,self.config)
        await self.holder.put_state('holder_count','0')
        await self.holder.put_state('holder_cache_ready','1')

    def transfer(self,block,sender,recipient,value):
        return {'contractAddress':CORE,'eventName':'Transfer','blockNumber':block,'blockHash':'0x'+f'{block:064x}',
            'txHash':'0x'+f'{block:064x}','logIndex':0,'blockTimestampMs':1791024000000,
            'payload':{'args':{'from':sender,'to':recipient,'value':str(value)}}}

    async def holder_view(self):
        async with self.database.connection() as connection:
            deltas=await (await connection.execute('''SELECT block_number,holder_address,delta_raw
                FROM onchain_holder_balance_deltas ORDER BY block_number,holder_address''')).fetchall()
            events=await (await connection.execute('SELECT tx_hash FROM onchain_event_logs ORDER BY tx_hash')).fetchall()
        return {'A':await self.holder.balance(A),'B':await self.holder.balance(B),
            'count':await self.holder.count(),'ready':await self.holder.ready(),'deltas':deltas,'events':events}

    async def fail_write(self,table,field,address):
        async with self.database.connection() as connection:
            await connection.execute('''CREATE FUNCTION audit_fail_write() RETURNS trigger LANGUAGE plpgsql AS $$
                DECLARE value jsonb; BEGIN
                    IF TG_OP='DELETE' THEN value=to_jsonb(OLD); ELSE value=to_jsonb(NEW); END IF;
                    IF value->>TG_ARGV[0]=TG_ARGV[1] THEN RAISE EXCEPTION 'synthetic ordinary write failure'; END IF;
                    IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
                END $$''')
            await connection.execute(sql.SQL('''CREATE TRIGGER audit_failure BEFORE INSERT OR UPDATE OR DELETE
                ON {} FOR EACH ROW EXECUTE FUNCTION audit_fail_write({},{})''').format(
                    sql.Identifier(table),sql.Literal(field),sql.Literal(address)))

    async def remove_fault(self,table):
        async with self.database.connection() as connection:
            await connection.execute(sql.SQL('DROP TRIGGER audit_failure ON {}').format(sql.Identifier(table)))

    async def test_failed_rewind_preserves_all_rows_then_retry_restores_original_transfer(self):
        entry=self.transfer(110,A,B,100)
        await self.projection.persist([self.transfer(100,ZERO,A,100),entry],True)
        before=await self.holder_view()
        async with self.database.connection() as connection:
            rows=await (await connection.execute('''SELECT holder_address FROM onchain_holder_balance_deltas
                WHERE block_number>=110 ORDER BY block_number DESC,log_index DESC''')).fetchall()
        await self.fail_write('onchain_token_balances','holder_address',rows[-1]['holder_address'])
        with self.assertRaises(psycopg.Error):await self.holder.rewind(110)
        self.assertEqual(await self.holder_view(),before)
        await self.remove_fault('onchain_token_balances')
        self.assertTrue(await self.holder.rewind(110))
        await self.projection.delete_from(110)
        await self.projection.persist([entry],True)
        self.assertEqual(await self.holder_view(),before)

    async def test_failed_transfer_does_not_commit_event_deduplication_key(self):
        await self.projection.persist([self.transfer(100,ZERO,A,100)],True)
        before=await self.holder_view()
        await self.fail_write('onchain_token_balances','holder_address',B)
        entry=self.transfer(110,A,B,100)
        with self.assertRaises(psycopg.Error):await self.projection.persist([entry],True)
        self.assertEqual(await self.holder_view(),before)
        await self.remove_fault('onchain_token_balances')
        await self.projection.persist([entry,entry],True)
        self.assertEqual((await self.holder.balance(A),await self.holder.balance(B),await self.holder.count()),(0,100,1))
        self.assertEqual(len((await self.holder_view())['events']),2)

    async def test_failed_rebuild_preserves_ready_projection(self):
        await self.projection.persist([self.transfer(100,ZERO,A,100),self.transfer(110,A,B,100)],True)
        before=await self.holder_view()
        await self.fail_write('onchain_token_balances','holder_address',B)
        with self.assertRaises(psycopg.Error):await self.holder.rebuild()
        self.assertEqual(await self.holder_view(),before)
        await self.remove_fault('onchain_token_balances')
        await self.holder.rebuild()
        self.assertEqual(await self.holder_view(),before)

    def signed(self,account,action,nonce):
        params={'action':action,'editorAddress':account.address,'ownerAddress':B,
            'alias':'atomic alias' if action=='upsert' else '','nonce':nonce,
            'issuedAt':datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')}
        signature=account.sign_message(encode_defunct(text=alias_message(params))).signature.hex()
        return {**params,'auth':{'nonce':nonce,'issuedAt':params['issuedAt'],'signature':'0x'+signature.removeprefix('0x')}}

    async def nonce_count(self,nonce):
        async with self.database.connection() as connection:
            return (await (await connection.execute('SELECT COUNT(*) AS count FROM governance_owner_alias_auth_nonces WHERE nonce=%s',
                (nonce,))).fetchone())['count']

    async def test_failed_signed_upsert_keeps_nonce_retryable_then_rejects_replay(self):
        payload=self.signed(Account.create(),'upsert','failed-upsert')
        app=create_app(aliases=AliasService(self.database))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://fixture') as api:
            await self.fail_write('governance_owner_aliases','owner_address',B)
            self.assertEqual((await api.post('/api/governance/owner-aliases',json=payload)).status_code,500)
            self.assertEqual(await self.nonce_count('failed-upsert'),0)
            await self.remove_fault('governance_owner_aliases')
            self.assertEqual((await api.post('/api/governance/owner-aliases',json=payload)).status_code,200)
            self.assertEqual((await api.post('/api/governance/owner-aliases',json=payload)).status_code,401)
            self.assertEqual(await self.nonce_count('failed-upsert'),1)

    async def test_failed_signed_delete_keeps_nonce_retryable_and_existing_alias(self):
        account=Account.create();service=AliasService(self.database)
        await service.upsert(account.address,B,'retained alias')
        payload=self.signed(account,'delete','failed-delete')
        app=create_app(aliases=service)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://fixture') as api:
            await self.fail_write('governance_owner_aliases','owner_address',B)
            self.assertEqual((await api.post('/api/governance/owner-aliases',json=payload)).status_code,500)
            self.assertEqual(await self.nonce_count('failed-delete'),0)
            self.assertEqual((await service.list(account.address,[B]))[0]['alias'],'retained alias')
            await self.remove_fault('governance_owner_aliases')
            self.assertEqual((await api.post('/api/governance/owner-aliases',json=payload)).json(),{'ok':True,'deleted':True})
            self.assertEqual(await service.list(account.address,[B]),[])
            self.assertEqual((await api.post('/api/governance/owner-aliases',json=payload)).status_code,401)

    async def test_concurrent_same_nonce_allows_one_mutation(self):
        payload=self.signed(Account.create(),'upsert','concurrent-alias')
        app=create_app(aliases=AliasService(self.database))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://fixture') as api:
            results=await asyncio.gather(*(api.post('/api/governance/owner-aliases',json=payload) for _ in range(2)))
        self.assertEqual(sorted(response.status_code for response in results),[200,401])
        self.assertEqual(await self.nonce_count('concurrent-alias'),1)

    async def test_successful_retained_holder_projection_remains_node_compatible(self):
        # The existing healthy-operation matrix stays independent from injected
        # failures, where preserving the old Node defect would be incorrect.
        from native_holder_db import qualify
        await qualify(self.database,self.url_fixture)

    async def test_retained_core_collection_replay_and_recovery_remain_node_compatible(self):
        from native_core_collector_db import qualify
        await qualify(self.database,self.url_fixture)


if __name__=='__main__':unittest.main()
