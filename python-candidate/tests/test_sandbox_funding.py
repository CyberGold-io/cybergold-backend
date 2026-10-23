"""Native faucet wire operations, durable outcomes and existing HTTP contract."""
import asyncio
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import uuid

import httpx

from cybergold_candidate.app import create_app
from cybergold_candidate.sandbox_funding import FundingError, SandboxFunding


ADDRESS = '0x1111111111111111111111111111111111111111'
OTHER = '0x2222222222222222222222222222222222222222'
GENERATION = '12345678-1234-4234-9234-123456789abc'
HASH = '0x' + 'ab' * 32
ETH = 10 * 10**18
TOKENS = (
    ('PAXG', '0x45804880De22913dAFE09f4980848ECE6EcbAf78', 5 * 10**18),
    ('XAUT', '0x68749665FF8D2d112Fa859AA293F07A622782F38', 5 * 10**6),
    ('USDC', '0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48', 10_000 * 10**6),
    ('USDT', '0xdAC17F958D2ee523a2206206994597C13D831ec7', 10_000 * 10**6),
)
WRITES = {'anvil_setBalance', 'anvil_dealERC20'}


def success(address=ADDRESS):
    return {'status':'ok', 'address':address, 'ethWei':str(ETH),
            'tokens':[{'symbol':symbol, 'amount':str(amount)} for symbol, _, amount in TOKENS],
            'dryRun':False}


class AnvilFixture:
    """A stateful JSON-RPC peer, with failures on either side of a write."""
    def __init__(self):
        self.calls = []
        self.native = {}
        self.tokens = {}
        self.chain = '0x7a6a'
        self.block_hash = HASH
        self.before = None
        self.after = None

    @property
    def writes(self):
        return [(method, params) for method, params in self.calls if method in WRITES]

    def fill(self, address=ADDRESS, extra=0):
        self.native[address.lower()] = ETH + extra
        for _, token, amount in TOKENS:
            self.tokens[(token.lower(), address.lower())] = amount + extra

    async def handle(self, request):
        self.calls.append(('request-authorization', request.headers.get('authorization')))
        payload = json.loads(request.content)
        method, params = payload['method'], payload['params']
        self.calls.append((method, params))
        if self.before:
            await self.before(method, params)
        if method == 'eth_chainId':
            result = self.chain
        elif method == 'web3_clientVersion':
            result = 'anvil/v1.8.5'
        elif method == 'anvil_nodeInfo':
            result = {'forkConfig': {'forkBlockNumber': hex(26_245_045)}}
        elif method == 'eth_getBlockByNumber':
            result = {'number':hex(26_245_045), 'hash':self.block_hash, 'timestamp':'0x6a000001'}
        elif method == 'eth_getBalance':
            result = hex(self.native.get(params[0].lower(), 0))
        elif method == 'eth_call':
            account = '0x' + params[0]['data'][-40:]
            result = '0x' + f"{self.tokens.get((params[0]['to'].lower(), account.lower()), 0):064x}"
        elif method == 'anvil_setBalance':
            self.native[params[0].lower()] = int(params[1], 16)
            result = None
        elif method == 'anvil_dealERC20':
            account, token, amount = params
            self.tokens[(token.lower(), account.lower())] = int(amount, 16)
            result = None
        else:
            raise AssertionError(f'unexpected native faucet RPC: {method}')
        if self.after:
            await self.after(method, params)
        return httpx.Response(200, json={'jsonrpc':'2.0', 'id':payload['id'], 'result':result})


class SandboxFundingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.generation_file = self.root / 'generation'
        self.generation_file.write_text(GENERATION + '\n')
        self.clock = 2000.0
        self.rpc = AnvilFixture()
        self.client = httpx.AsyncClient(transport=httpx.MockTransport(self.rpc.handle))
        self.services = []
        self.faucet = self.open()

    def open(self, **changes):
        settings = {'client':self.client, 'enabled':True, 'rpc_url':'http://fixture.invalid',
                    'rpc_authorization':'Bearer fixture-native-only', 'state_root':self.root / 'state',
                    'generation_file':self.generation_file, 'now':lambda: self.clock}
        settings.update(changes)
        result = SandboxFunding(**settings)
        self.services.append(result)
        return result

    async def asyncTearDown(self):
        for service in self.services:
            await service.close()
        await self.client.aclose()
        self.directory.cleanup()

    async def fund(self, request_id=None, *, address=ADDRESS, service=None):
        return await (service or self.faucet).fund(address, request_id or str(uuid.uuid4()), '192.0.2.7')

    @property
    def database(self):
        return self.root / 'state' / 'generations' / GENERATION / 'faucet.sqlite3'

    def row(self, request_id):
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.row_factory = sqlite3.Row
            value = connection.execute('SELECT * FROM requests WHERE request_id = ?', (request_id,)).fetchone()
            return dict(value) if value else None

    async def test_native_assignments_use_absolute_fixed_targets_and_no_transactions(self):
        self.assertEqual(await self.fund(), success())
        self.assertEqual(self.rpc.writes, [
            ('anvil_setBalance', [ADDRESS, hex(ETH)]),
            *[('anvil_dealERC20', [ADDRESS, token, hex(amount)]) for _, token, amount in TOKENS],
        ])
        self.assertEqual(self.rpc.native[ADDRESS], ETH)
        for _, token, amount in TOKENS:
            self.assertEqual(self.rpc.tokens[(token.lower(), ADDRESS)], amount)
        self.assertTrue(all(value == 'Bearer fixture-native-only' for method, value in self.rpc.calls
                            if method == 'request-authorization'))
        self.assertFalse(any(method.startswith('eth_send') or method == 'eth_getTransactionReceipt'
                             for method, _ in self.rpc.calls))

    async def test_above_target_balances_are_preserved_and_only_deficits_are_assigned(self):
        self.rpc.fill(extra=123)
        _, token, target = TOKENS[1]
        self.rpc.tokens[(token.lower(), ADDRESS)] = target - 1
        self.assertEqual(await self.fund(), success())
        self.assertEqual(self.rpc.writes, [('anvil_dealERC20', [ADDRESS, token, hex(target)])])
        self.assertEqual(self.rpc.native[ADDRESS], ETH + 123)
        for _, current, amount in TOKENS:
            self.assertEqual(self.rpc.tokens[(current.lower(), ADDRESS)], amount if current == token else amount + 123)

    async def test_completed_replay_survives_reopen_without_refilling_spent_balances(self):
        request_id = str(uuid.uuid4())
        first = await self.fund(request_id)
        self.rpc.native[ADDRESS] = ETH - 1
        self.rpc.calls.clear()
        await self.faucet.close()
        reopened = self.open()
        self.assertEqual(await self.fund(request_id, service=reopened), first)
        self.assertEqual(self.rpc.writes, [])
        self.assertEqual(self.rpc.native[ADDRESS], ETH - 1)
        self.assertEqual(self.row(request_id)['status'], 'completed')

    async def test_request_id_cannot_be_reused_for_another_wallet(self):
        request_id = str(uuid.uuid4())
        await self.fund(request_id)
        self.rpc.calls.clear()
        with self.assertRaises(FundingError) as failure:
            await self.fund(request_id, address=OTHER)
        self.assertEqual(failure.exception.code, 'REQUEST_CONFLICT')
        self.assertEqual(self.rpc.writes, [])

    async def test_noop_during_cooldown_does_not_renew_it(self):
        original = str(uuid.uuid4())
        await self.fund(original)
        self.clock += 500
        noop = str(uuid.uuid4())
        self.rpc.calls.clear()
        self.assertEqual(await self.fund(noop), success())
        self.assertEqual(self.rpc.writes, [])
        self.assertIsNone(self.row(noop)['funded_at'])
        self.rpc.native[ADDRESS] = ETH - 1
        with self.assertRaises(FundingError) as failure:
            await self.fund()
        self.assertEqual((failure.exception.code, failure.exception.retry), ('RATE_LIMITED', 400))
        self.assertEqual(self.rpc.writes, [])
        self.clock += 400
        self.assertEqual(await self.fund(), success())
        self.assertEqual(self.rpc.writes, [('anvil_setBalance', [ADDRESS, hex(ETH)])])

    async def test_partial_write_failure_stays_terminal_and_new_id_fills_only_missing_assets(self):
        async def fail_xaut(method, params):
            if method == 'anvil_dealERC20' and params[1] == TOKENS[1][1]:
                raise httpx.ReadTimeout('fixture-private-response-lost')
        self.rpc.before = fail_xaut
        request_id = str(uuid.uuid4())
        with self.assertRaises(FundingError) as failure:
            await self.fund(request_id)
        self.assertEqual(failure.exception.code, 'REQUEST_UNCERTAIN')
        self.assertTrue(failure.exception.replace)
        self.assertEqual(self.row(request_id)['status'], 'uncertain')
        self.rpc.before = None
        self.rpc.calls.clear()
        with self.assertRaises(FundingError) as replay:
            await self.fund(request_id)
        self.assertEqual(replay.exception.code, 'REQUEST_UNCERTAIN')
        self.assertEqual(self.rpc.writes, [])
        self.assertEqual(await self.fund(), success())
        self.assertEqual(self.rpc.writes, [
            ('anvil_dealERC20', [ADDRESS, token, hex(amount)]) for _, token, amount in TOKENS[1:]
        ])

    async def test_lost_response_after_an_applied_write_is_safe_to_top_up_again(self):
        async def lost_response(method, _params):
            if method == 'anvil_setBalance':
                raise httpx.ReadTimeout('fixture-private-response-lost')
        self.rpc.after = lost_response
        with self.assertRaises(FundingError) as failure:
            await self.fund()
        self.assertEqual(failure.exception.code, 'REQUEST_UNCERTAIN')
        self.assertEqual(self.rpc.native[ADDRESS], ETH)
        self.rpc.after = None
        self.rpc.calls.clear()
        await self.fund()
        self.assertEqual(self.rpc.writes, [
            ('anvil_dealERC20', [ADDRESS, token, hex(amount)]) for _, token, amount in TOKENS
        ])
        self.assertEqual(self.rpc.native[ADDRESS], ETH)

    async def test_failed_balance_read_records_failure_before_any_write(self):
        async def failed_read(method, _params):
            if method == 'eth_call':
                raise httpx.ReadTimeout('fixture-private-provider')
        self.rpc.before = failed_read
        request_id = str(uuid.uuid4())
        with self.assertRaises(FundingError) as failure:
            await self.fund(request_id)
        self.assertEqual(failure.exception.code, 'FUNDING_FAILED')
        self.assertEqual(self.rpc.writes, [])
        self.assertEqual(self.row(request_id)['status'], 'failed')
        self.rpc.before = None
        with self.assertRaises(FundingError) as replay:
            await self.fund(request_id)
        self.assertEqual(replay.exception.code, 'FUNDING_FAILED')
        self.assertEqual(self.rpc.writes, [])

    async def test_successful_assignments_do_not_depend_on_postwrite_balance_reads(self):
        mutation_started = False
        async def balances_unavailable_after_write(method, _params):
            nonlocal mutation_started
            if method in WRITES:
                mutation_started = True
            elif mutation_started and method in ('eth_getBalance', 'eth_call'):
                raise httpx.ReadTimeout('fixture-private-balance-reader-unavailable')
        self.rpc.before = balances_unavailable_after_write
        request_id = str(uuid.uuid4())
        self.assertEqual(await self.fund(request_id), success())
        self.assertEqual(len(self.rpc.writes), 5)
        self.assertEqual([method for method, _ in self.rpc.calls if method in ('eth_getBalance', 'eth_call')],
                         ['eth_getBalance', 'eth_call', 'eth_call', 'eth_call', 'eth_call'])
        self.assertEqual(self.row(request_id)['status'], 'completed')
        self.assertEqual(self.row(request_id)['funded_at'], self.clock)

    async def test_cancelled_write_is_uncertain_and_releases_operation_for_safe_new_id(self):
        entered = asyncio.Event()
        cancelled = asyncio.Event()
        async def blocked_write(method, _params):
            if method == 'anvil_setBalance':
                entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()
        self.rpc.before = blocked_write
        request_id = str(uuid.uuid4())
        task = asyncio.create_task(self.fund(request_id))
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(cancelled.is_set())
        self.assertEqual(self.row(request_id)['status'], 'uncertain')
        self.rpc.before = None
        self.assertEqual(await asyncio.wait_for(self.fund(), 1), success())

    async def test_operation_lock_serializes_two_api_instances(self):
        entered, release = asyncio.Event(), asyncio.Event()
        first_write = True
        async def blocked_write(method, _params):
            nonlocal first_write
            if method == 'anvil_setBalance' and first_write:
                first_write = False
                entered.set()
                await release.wait()
        self.rpc.before = blocked_write
        other_service = self.open()
        first = asyncio.create_task(self.fund())
        await asyncio.wait_for(entered.wait(), 1)
        second = asyncio.create_task(self.fund(address=OTHER, service=other_service))
        await asyncio.sleep(.03)
        self.assertFalse(second.done())
        self.assertEqual(len(self.rpc.writes), 1)
        release.set()
        self.assertEqual(await asyncio.wait_for(first, 1), success())
        self.assertEqual(await asyncio.wait_for(second, 1), success(OTHER))

    async def test_wrong_chain_is_rejected_before_balance_mutation(self):
        self.rpc.chain = '0x1'
        with self.assertRaises(FundingError) as failure:
            await self.fund()
        self.assertEqual(failure.exception.code, 'CHAIN_UNAVAILABLE')
        self.assertEqual(self.rpc.writes, [])

    async def test_checkpoint_reset_is_rejected_before_mutation(self):
        await self.fund()
        self.rpc.calls.clear()
        self.rpc.block_hash = '0x' + 'cd' * 32
        with self.assertRaises(FundingError) as failure:
            await self.fund(address=OTHER)
        self.assertEqual(failure.exception.code, 'CHAIN_UNAVAILABLE')
        self.assertEqual(self.rpc.writes, [])

    async def test_generation_rotation_uses_fresh_ledger_and_preserves_old_outcomes(self):
        request_id = str(uuid.uuid4())
        await self.fund(request_id)
        old_row = self.row(request_id)
        self.assertEqual(old_row['funded_at'], 2000.0)
        new_generation = str(uuid.uuid4())
        replacement = self.generation_file.with_suffix('.replacement')
        replacement.write_text(new_generation + '\n')
        replacement.replace(self.generation_file)
        self.rpc.native.clear()
        self.rpc.tokens.clear()
        self.rpc.block_hash = '0x' + 'cd' * 32
        self.rpc.calls.clear()
        self.clock += 1

        # Reuse the running API instance and request ID. A replaced generation
        # file must select new state without replaying the old successful row.
        self.assertEqual(await self.fund(request_id), success())
        self.assertEqual(len(self.rpc.writes), 5)
        self.assertEqual(self.row(request_id), old_row)
        new_database = self.root / 'state' / 'generations' / new_generation / 'faucet.sqlite3'
        with closing(sqlite3.connect(new_database)) as connection:
            self.assertEqual(connection.execute('SELECT status,funded_at FROM requests WHERE request_id=?',
                                               (request_id,)).fetchone(), ('completed', 2001.0))
        with closing(sqlite3.connect(self.database)) as connection:
            checkpoint = json.loads(connection.execute('SELECT value FROM metadata WHERE key=?',
                                                       ('chainCheckpoint',)).fetchone()[0])
        self.assertEqual(checkpoint['blockHash'], HASH)

    async def test_recovered_legacy_reservation_is_uncertain_without_replay(self):
        request_id = str(uuid.uuid4())
        await self.fund()  # Create the existing generation schema and checkpoint.
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute('INSERT INTO requests(request_id,address_key,requester_ip,created_at,status) '
                               "VALUES (?,?,?,?,'reserved')", (request_id, OTHER, '192.0.2.9', 1000))
        self.rpc.calls.clear()
        reopened = self.open()
        with self.assertRaises(FundingError) as failure:
            await self.fund(request_id, address=OTHER, service=reopened)
        self.assertEqual(failure.exception.code, 'REQUEST_UNCERTAIN')
        self.assertEqual(self.row(request_id)['status'], 'uncertain')
        self.assertEqual(self.rpc.writes, [])

    async def test_legacy_completed_rows_keep_results_without_inventing_cooldown(self):
        self.database.parent.mkdir(parents=True)
        request_id = str(uuid.uuid4())
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.executescript('''
                CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL) STRICT;
                CREATE TABLE requests(request_id TEXT PRIMARY KEY,address_key TEXT NOT NULL,
                    requester_ip TEXT NOT NULL,created_at INTEGER NOT NULL,status TEXT NOT NULL,
                    http_status INTEGER,error_code TEXT,error_reason TEXT,result_json TEXT) STRICT;
                PRAGMA user_version = 1;
            ''')
            connection.execute('INSERT INTO metadata VALUES (?,?)', ('generation', GENERATION))
            connection.execute('INSERT INTO requests VALUES (?,?,?,?,?,?,?,?,?)',
                (request_id, ADDRESS, '192.0.2.7', 1000, 'completed', 200, None, None, json.dumps(success())))
        self.assertEqual(await self.fund(request_id), success())
        self.assertEqual(self.rpc.writes, [])
        self.assertIsNone(self.row(request_id)['funded_at'])
        self.assertEqual(await self.fund(), success())
        with closing(sqlite3.connect(self.database)) as connection, connection:
            self.assertEqual(connection.execute('PRAGMA user_version').fetchone()[0], 2)

    async def test_http_route_preserves_success_and_uncertain_replacement_contract(self):
        app = create_app(faucet_service=self.faucet)
        headers = {'x-real-ip':'192.0.2.7', 'x-forwarded-for':'192.0.2.7'}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://fixture') as api:
            response = await api.post('/api/faucet', json={'address':ADDRESS,'requestId':str(uuid.uuid4())}, headers=headers)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), success())
            self.assertEqual(response.headers['cache-control'], 'no-store')
            async def fail_write(method, _params):
                if method == 'anvil_setBalance':
                    raise httpx.ReadTimeout('fixture-private-provider')
            self.rpc.before = fail_write
            response = await api.post('/api/faucet', json={'address':OTHER,'requestId':str(uuid.uuid4())}, headers=headers)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['code'], 'REQUEST_UNCERTAIN')
        self.assertEqual(response.headers['x-cybergold-faucet-request-id'], 'replace')
        self.assertRegex(response.json()['correlationId'], r'^[0-9a-f-]{36}$')
        self.assertNotIn('fixture-private', response.text)
        self.assertNotIn('fixture-native-only', response.text)


if __name__ == '__main__':
    unittest.main()
