"""Read-only estimate service: scope acquisition, history read, then pure math."""
from copy import deepcopy
from .quote_flow import stage
from .routing_encoding import ZERO
from .quoter.reuse_estimate import populate_estimate_packet


class CachedEconomicEstimates:
    def __init__(self, store, core, *, observe_scope=None):
        self.store, self.core, self.observe_scope = store, core, observe_scope

    async def get_model(self, request):
        packet = {'namespace': 'trade', 'intent': deepcopy(request), 'models': []}
        try:
            if self.observe_scope is not None:
                with stage('estimate.scope'):
                    await self.observe_scope()
            counter = ZERO if request.get('native') else request['counterToken']
            buy = request['side'] == 'buy'
            economic = {'intent': 0 if buy else 1,
                'inputs': [{'currency': counter if buy else self.core, 'amount': request['amount']}],
                'outputCurrency': self.core if buy else counter}
            with stage('cache.capture', kind='cpu'):
                scope = self.store.capture_scope(economic)
            with stage('estimate.read'):
                neighbors = await self.store.neighbors(economic, scope=scope)
            with stage('estimate.calculate', kind='cpu'):
                populate_estimate_packet(packet, request, neighbors)
        except Exception:
            # Advisory lookup errors retain the same empty/partial hint. They
            # never initiate inventory hydration, head reads, RPC or SDK work.
            pass
        return packet
