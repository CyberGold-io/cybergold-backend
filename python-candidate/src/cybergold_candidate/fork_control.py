"""Retained fork RPC/DB control order; the engine supplies its transport."""
from .fork_recovery import read_generation, prepare_generation, apply_generation


class ForkControl:
    def __init__(self, database, config, runtime, rpc_factory):
        self.database, self.config, self.runtime = database, config, runtime
        self.rpc_factory = rpc_factory

    def sandbox_config(self):
        if not self.config or self.config['chainId'] != 31338:
            raise ValueError('Sandbox fork recovery requires the chain-31338 indexer')
        return self.config

    async def status(self):
        config = self.sandbox_config()
        await self.database.ensure_schema()
        async with self.database.connection() as connection:
            stored = await read_generation(connection, config['coreAddress'].lower())
        if stored is None:
            return None
        return {'generation': stored['anchor']['generation'], 'forkBlock': str(stored['anchor']['forkBlock']),
            'forkBlockHash': stored['anchor']['forkBlockHash'], 'status': stored['status']}

    async def transition(self, input):
        config = self.sandbox_config()
        await self.database.ensure_schema()
        async with self.database.advisory_lock('onchain-indexer:31338:' + config['coreAddress'].lower()) as acquired:
            if not acquired:
                return {'status': 'busy'}
            client = self.rpc_factory(config)
            try:
                if await client.chain_id() != 31338:
                    raise ValueError('Sandbox indexer RPC chain ID differs')
                current = input['current']
                block = await client.block(current['forkBlock'])
                if block['number'] != current['forkBlock'] or block['hash'].lower() != current['forkBlockHash'].lower():
                    raise ValueError('current Sandbox fork-point header differs')
                if input['action'] == 'prepare':
                    async with self.database.connection() as connection:
                        async with connection.transaction():
                            return await prepare_generation(connection, config['coreAddress'], current)
                common_hash = None
                previous = input['previous']
                if previous['forkBlock'] <= current['forkBlock']:
                    block = await client.block(previous['forkBlock'])
                    if block['number'] != previous['forkBlock']:
                        raise ValueError('previous Sandbox fork-point header number differs')
                    common_hash = block['hash']
                async with self.database.connection() as connection:
                    async with connection.transaction():
                        result = await apply_generation(connection, config['coreAddress'], previous,
                            current, config['startBlock'], common_hash)
                self.runtime['lastReconciledAtMs'] = 0
                self.runtime['lastReconciliationReceipt'] = None
                return result
            finally:
                await client.close()
