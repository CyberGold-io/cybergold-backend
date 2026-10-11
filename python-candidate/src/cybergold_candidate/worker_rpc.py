"""Standard Web3 direct-provider transport for the retained raw-log range policy."""
from aiohttp import ClientResponseError
import httpx
from web3.exceptions import Web3RPCError

from .rpc_transport import rpc_provider


def approved_range_reduction(error):
    seen=set();current=error
    for _ in range(16):
        if current is None or id(current) in seen:return False
        seen.add(id(current))
        if isinstance(current,ClientResponseError) and current.status==413:return True
        if isinstance(current,httpx.HTTPStatusError) and current.response.status_code==413:return True
        if isinstance(current,Web3RPCError):
            code=current.rpc_response.get('error',{}).get('code') if isinstance(current.rpc_response,dict) else None
            if type(code) in (int,float) and code in (-32005,-32016):return True
        current=getattr(current,'__cause__',None)
    return False


class RawLogTransport:
    def __init__(self,url,authorization=None,timeout_seconds=15):
        self.provider=rpc_provider(url,authorization,timeout_seconds)

    async def logs(self,address,range):
        response=await self.provider.make_request('eth_getLogs',[{
            'address':address,'fromBlock':hex(range['fromBlock']),'toBlock':hex(range['toBlock'])}])
        if 'error' in response:raise Web3RPCError('Raw log RPC request failed',rpc_response=response)
        return response['result']

    async def close(self):await self.provider.disconnect()
