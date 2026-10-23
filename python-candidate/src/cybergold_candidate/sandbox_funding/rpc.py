"""Private native Anvil operations; no signing, public RPC, cache or retries."""
import httpx


class AnvilRpc:
    def __init__(self, client, url, authorization=None):
        self.owned_client = client is None
        self.client = client if client is not None else httpx.AsyncClient()
        self.url = url
        self.headers = {'Authorization': authorization} if authorization else {}
        self.next_id = 0

    async def __call__(self, method, params):
        self.next_id += 1
        response = await self.client.post(self.url, headers=self.headers, follow_redirects=False, timeout=2,
            json={'jsonrpc': '2.0', 'id': self.next_id, 'method': method, 'params': params})
        response.raise_for_status()
        value = response.json()
        if 'error' in value:
            raise ValueError(f'Anvil {method} failed')
        return value['result']

    async def close(self):
        if self.owned_client:
            await self.client.aclose()
