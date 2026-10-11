import json
import logging
import unittest
from uuid import UUID

import httpx

from cybergold_candidate.app import create_app


class SafeHttpContract(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_view_preserves_body_and_no_store(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(503))) as supplier:
            app = create_app(client=supplier)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://fixture') as api:
                response = await api.get('/api/activity/safe')
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), {'enabled': False, 'events': []})
                self.assertEqual(response.headers['Cache-Control'], 'no-store')

    async def test_private_driver_error_is_replaced_with_correlation(self):
        async def fail():
            raise RuntimeError('private-database-url-and-token-must-not-leak')

        async with httpx.AsyncClient() as supplier:
            app = create_app(client=supplier, safe_activity=fail)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://fixture') as api:
                with self.assertLogs('cybergold.candidate', level=logging.ERROR) as logs:
                    response = await api.get('/api/activity/safe')
                self.assertEqual(response.status_code, 500)
                body = response.json()
                self.assertEqual(body['error'], 'Safe activity is temporarily unavailable.')
                self.assertEqual(UUID(body['correlationId']).version, 4)
                self.assertEqual(response.headers['Cache-Control'], 'no-store')
                self.assertNotIn('private-database', response.text + str(logs.output))
                fields = json.loads(logs.records[0].message)
                self.assertEqual(fields, {'correlationId': body['correlationId'], 'context': 'safe-activity',
                                          'errorClassification': 'unexpected-error'})


if __name__ == '__main__':
    unittest.main()
