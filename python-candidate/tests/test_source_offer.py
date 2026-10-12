# SPDX-License-Identifier: AGPL-3.0-only
import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from cybergold_candidate.app import create_app
from cybergold_candidate.environment import load_environment
from cybergold_candidate.protocol_config import ProtocolConfiguration
from cybergold_candidate.runtime import create_configured_app
from cybergold_candidate.source_offer import OFFERS, REPOSITORY


class SourceOfferTests(unittest.IsolatedAsyncioTestCase):
    async def read_source(self, app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://fixture') as api:
            get = await api.get('/source')
            head = await api.head('/source')
            metrics = await api.get('/metrics')
        self.assertEqual(get.status_code, 200)
        self.assertEqual(head.status_code, 200)
        self.assertEqual(head.content, b'')
        self.assertEqual(get.headers['cache-control'], 'no-store')
        self.assertIn('</source>', metrics.headers['link'])
        self.assertIn('text/plain', metrics.headers['content-type'])
        return get

    async def test_configured_runtime_serves_its_own_retained_version(self):
        class Database:
            async def close(self): pass
            def connection(self): raise AssertionError('Source offer opened a database')
        version = OFFERS[0]['version']
        settings = load_environment({'NEXT_PUBLIC_CHAIN_ID': '31338',
            'NEXT_PUBLIC_CORE_DIAMOND_ADDRESS': '0x' + '1'*40,
            'NEXT_PUBLIC_RPC_URL': 'http://fixture.invalid'})
        async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda request: (_ for _ in ()).throw(AssertionError('Source offer contacted provider')))) as provider:
            with patch.dict(os.environ, {'CYBERGOLD_BACKEND_COMMIT': version,
                    'CYBERGOLD_BACKEND_BEARER_TOKEN': 'fixture-private-not-source'}), \
                    patch.object(ProtocolConfiguration, 'start', new_callable=AsyncMock):
                app = create_configured_app(settings, Database(), provider)
                async with app.router.lifespan_context(app):
                    response = await self.read_source(app)
        self.assertEqual(response.json()['version'], version)
        self.assertEqual(response.json()['downloadUrl'], OFFERS[0]['downloadUrl'])
        self.assertEqual(response.json()['sha256'], OFFERS[0]['sha256'])
        self.assertNotIn('fixture-private', response.text)
        self.assertIn(OFFERS[0]['downloadUrl'], response.headers['link'])

    async def test_subsequent_public_commit_has_exact_source_archive(self):
        version = 'e'*40
        async with httpx.AsyncClient() as provider:
            app = create_app(client=provider, release=version)
            async with app.router.lifespan_context(app):
                response = await self.read_source(app)
        self.assertEqual(response.json()['downloadUrl'], REPOSITORY + '/archive/' + version + '.tar.gz')
        self.assertIsNone(response.json()['sha256'])

    async def test_local_build_without_release_remains_available(self):
        async with httpx.AsyncClient() as provider:
            app = create_app(client=provider)
            async with app.router.lifespan_context(app):
                response = await self.read_source(app)
        self.assertIsNone(response.json()['version'])
        self.assertIsNone(response.json()['downloadUrl'])
        self.assertEqual(response.json()['repository'], REPOSITORY)

    async def test_source_header_preserves_stream_messages(self):
        from cybergold_candidate.source_offer import SourceLinkMiddleware
        async def stream(scope, receive, send):
            await send({'type': 'http.response.start', 'status': 200, 'headers': [(b'link', b'<other>; rel="next"')]})
            await send({'type': 'http.response.body', 'body': b'first', 'more_body': True})
            await send({'type': 'http.response.body', 'body': b'second', 'more_body': False})
        messages = []
        async def send(message): messages.append(message)
        async def receive(): return {'type': 'http.request'}
        await SourceLinkMiddleware(stream)({'type': 'http'}, receive, send)
        self.assertEqual(messages[1:], [
            {'type': 'http.response.body', 'body': b'first', 'more_body': True},
            {'type': 'http.response.body', 'body': b'second', 'more_body': False}])
        self.assertEqual(messages[0]['headers'][0], (b'link', b'<other>; rel="next"'))


if __name__ == '__main__': unittest.main()
