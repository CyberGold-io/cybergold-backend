"""A physical JSON-client disconnect ends its owned quotation/preparation."""
import asyncio
import json
from types import SimpleNamespace
import unittest

from cybergold_candidate.app import create_app
from test_economic_quote_api import service, SharedStore
from test_universal_quote import request, USER, PAXG


class EconomicHttpLifetimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_json_disconnect_cancels_and_drains_quote_preparation_and_estimate(self):
        quoter, quotes = service(SharedStore())
        self.addAsyncCleanup(quotes.close)
        economic = {key: request()[key] for key in ('intent', 'inputs', 'outputCurrency')}
        selected = await quoter.quote(economic)
        cases = [('/api/economic-quotes', economic),
                 ('/api/tx-preparations', {'quote': selected, 'sender': USER, 'recipient': USER}),
                 ('/api/economic-estimates', {'side': 'buy', 'mode': 'exact-in',
                                              'counterToken': PAXG, 'amount': '1000'}),
                 ('/api/quotes/trade/model', {'side': 'buy', 'mode': 'exact-in',
                                              'counterToken': PAXG, 'amount': '1000'})]
        for path, payload in cases:
            with self.subTest(path=path):
                entered, drained = asyncio.Event(), asyncio.Event()
                async def pending(*_args, **_kwargs):
                    entered.set()
                    try:
                        await asyncio.Event().wait()
                    finally:
                        drained.set()
                app = create_app(economic_quotes=SimpleNamespace(get=pending),
                    transaction_preparation=SimpleNamespace(prepare=pending),
                    trade_quotes=SimpleNamespace(get_model=pending))
                incoming = asyncio.Queue()
                incoming.put_nowait({'type': 'http.request', 'body': json.dumps(payload).encode(),
                                     'more_body': False})
                sent = []
                async def send(message):
                    sent.append(message)
                scope = {'type': 'http', 'asgi': {'version': '3.0', 'spec_version': '2.4'},
                    'http_version': '1.1', 'method': 'POST', 'scheme': 'http', 'path': path,
                    'raw_path': path.encode(), 'query_string': b'', 'root_path': '',
                    'headers': [(b'content-type', b'application/json')],
                    'server': ('test', 80), 'client': ('127.0.0.1', 1)}
                task = asyncio.create_task(app(scope, incoming.get, send))
                try:
                    await asyncio.wait_for(entered.wait(), 1)
                    incoming.put_nowait({'type': 'http.disconnect'})
                    await asyncio.wait_for(task, .2)
                    self.assertTrue(drained.is_set())
                    self.assertEqual([message['status'] for message in sent
                                      if message['type'] == 'http.response.start'], [499])
                finally:
                    if not task.done():
                        task.cancel()
                    await asyncio.gather(task, return_exceptions=True)


class LegacyStreamLifetimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_asgi_23_and_24_idle_disconnect_drains_all_four_legacy_streams(self):
        from test_quote_intent import request as intent_request
        from test_trade_quote import request as trade_request
        from test_uniswap_market import B, C
        cases = [('/api/quotes/routes/stream', {'mode': 'exact-in', 'targets': [
                    {'inputAsset': PAXG, 'outputAsset': B, 'amount': '1000'}]}),
                 ('/api/quotes/intent/stream', intent_request('issue-exact-in')),
                 ('/api/quotes/trade/stream', trade_request()),
                 ('/api/quotes/market/stream', {'side': 'sell', 'mode': 'exact-in',
                    'counterToken': B, 'amount': '1000', 'adapter': C, 'recipient': B,
                    'deadline': '9999999999', 'slippageBps': 50})]
        for spec in ('2.3', '2.4'):
            for path, payload in cases:
                with self.subTest(spec=spec, path=path):
                    entered, delivered, drained = asyncio.Event(), asyncio.Event(), asyncio.Event()
                    async def pending(_request, on_update=None):
                        entered.set()
                        try:
                            await on_update({'type': 'progress', 'completedCandidates': 0})
                            await asyncio.Event().wait()
                        finally:
                            drained.set()
                    provider = SimpleNamespace(get=pending)
                    app = create_app(route_search=provider, quote_intent=provider,
                                     trade_quotes=provider, market_quotes=provider)
                    incoming = asyncio.Queue()
                    incoming.put_nowait({'type': 'http.request', 'body': json.dumps(payload).encode(),
                                         'more_body': False})
                    sent = []
                    async def send(message):
                        sent.append(message)
                        if message['type'] == 'http.response.body' and message.get('body'):
                            delivered.set()
                    scope = {'type': 'http', 'asgi': {'version': '3.0', 'spec_version': spec},
                        'http_version': '1.1', 'method': 'POST', 'scheme': 'http', 'path': path,
                        'raw_path': path.encode(), 'query_string': b'', 'root_path': '',
                        'headers': [(b'content-type', b'application/json')],
                        'server': ('test', 80), 'client': ('127.0.0.1', 1)}
                    task = asyncio.create_task(app(scope, incoming.get, send))
                    try:
                        await asyncio.wait_for(entered.wait(), 1)
                        await asyncio.wait_for(delivered.wait(), 1)
                        self.assertFalse(task.done())
                        self.assertFalse(drained.is_set())
                        incoming.put_nowait({'type': 'http.disconnect'})
                        await asyncio.wait_for(task, 1)
                        self.assertTrue(drained.is_set())
                        self.assertEqual([message['status'] for message in sent
                                          if message['type'] == 'http.response.start'], [200])
                    finally:
                        if not task.done():
                            task.cancel()
                        await asyncio.gather(task, return_exceptions=True)


if __name__ == '__main__':
    unittest.main()
