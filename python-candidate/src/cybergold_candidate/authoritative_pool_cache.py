"""Legacy cache envelope, with all observations refreshed by the server."""
import asyncio
import json

from .pool_cache import PoolCache
from .pool_producer import PoolIdentifier, identifier_from_pool
from .retained_reads import cached_pool_identifiers
from .supplier_dispatch import dispatch


class AuthoritativePoolCache(PoolCache):
    def __init__(self, database, producer):
        super().__init__(database)
        self.producer = producer

    async def refresh(self, entries):
        # Existing browsers may still send observation fields. Only identifiers
        # enter the producer; factory/price/liquidity/existence are never hints.
        identifiers = {}
        for entry in entries:
            token_a = entry.get('tokenA', entry.get('token0'))
            token_b = entry.get('tokenB', entry.get('token1'))
            raw = {key: entry[key] for key in ('protocol','id','poolId','poolManager','tickSpacing','hooks') if key in entry}
            if 'protocol' not in raw and entry.get('dex') in ('uniswap_v2','uniswap_v4'):
                raw['protocol'] = entry['dex'].removeprefix('uniswap_')
            identifier = PoolIdentifier.model_validate({**raw,'tokenA': token_a,'tokenB': token_b,
                'fee': entry['fee']}).model_dump(exclude_unset=True,exclude_none=True)
            registry = getattr(self.producer,'registry',None)
            known = registry.inventory.get(identifier.get('id') or identifier.get('poolId')) if registry else None
            if known and known['protocol'] == (identifier.get('protocol') or 'v3'):
                identifier = identifier_from_pool(known)
            key = self.identity(identifier)
            identifiers[key] = identifier
        return await dispatch(identifiers.values(), self.producer.get)

    def identity(self, identifier):
        protocol = identifier.get('protocol') or 'v3'
        pair = ':'.join(sorted((identifier['tokenA'].lower(),identifier['tokenB'].lower())))
        if protocol == 'v4':
            from .uniswap_v4 import v4_pool_id, POOL_MANAGER
            registry = getattr(self.producer,'registry',None)
            manager = identifier.get('poolManager') or (registry.get_rpc().pool_manager
                if registry else POOL_MANAGER)
            key = (*sorted((identifier['tokenA'].lower(),identifier['tokenB'].lower())),
                   identifier['fee'],identifier['tickSpacing'],identifier['hooks'])
            return f'v4:{manager.lower()}:{v4_pool_id(key).lower()}'
        if identifier.get('id'):
            return f'{protocol}:{identifier["id"].lower()}'
        registry = getattr(self.producer,'registry',None)
        rpc = registry.get_rpc() if registry else getattr(self.producer,'rpc',None)
        factory = getattr(rpc,'v2_factory' if protocol == 'v2' else 'factory','')
        return f'{protocol}:{factory.lower()}:{pair}:{identifier["fee"]}'

    async def list(self, chain_id, dex, pairs):
        if chain_id != self.producer.chain_id:
            return []
        async with asyncio.timeout(15):
            explicit = dex != 'uniswap_v3' or any(pair.get('protocol') for pair in pairs)
            if not explicit:
                prior = await super().list(chain_id, dex, pairs)
            else:
                await self.database.ensure_schema()
                prior = await cached_pool_identifiers(self.database,chain_id,dex,pairs)
                if dex in ('uniswap','uniswap_v3'):
                    prior += [{**row,'protocol':'v3'} for row in await super().list(chain_id,'uniswap_v3',pairs)]
                registry = getattr(self.producer,'registry',None)
                if registry:
                    await registry.ensure_loaded(wait=True)
                    selected = {tuple(sorted((pair['tokenA'].lower(),pair['tokenB'].lower()))) for pair in pairs}
                    prior += [identifier_from_pool(pool) for pool in registry.inventory.values()
                              if (pool['protocol'] == 'v4' or pool.get('address')) and
                              (dex == 'uniswap' or dex == 'uniswap_'+pool['protocol']) and
                              tuple(sorted((pool['token0']['address'].lower(),pool['token1']['address'].lower()))) in selected]
            observations = await self.refresh(prior)
            # Do not publish previously browser-owned fields on outage. A
            # canonical empty factory result supersedes stale existence too.
            return [{**{key: value for key, value in row.items() if key != 'context'},
                     'successCount': 0, 'lastCheckedAt': row['context']['observedAt'],
                     **({'liquidityCheckedAt': row['context']['observedAt']} if row['exists'] else {})}
                    for row in observations if self.matches(row,pairs)]

    @staticmethod
    def matches(row,pairs):
        for pair in pairs:
            if sorted((pair['tokenA'].lower(),pair['tokenB'].lower())) != [row['token0'].lower(),row['token1'].lower()]:
                continue
            fields = ('protocol','id','poolId','poolManager','fee','tickSpacing','hooks')
            if all(key not in pair or str(pair[key]).lower() == str(row.get(key)).lower() for key in fields):
                return True
        return False

    async def record(self, entries):
        async with asyncio.timeout(15):
            observations = await self.refresh(entries)
            await self.database.ensure_schema()
            for row in observations:
                if row.get('protocol'):
                    identifier = identifier_from_pool(row['pool']) if row.get('pool') else {
                        'protocol':row['protocol'],'tokenA':row['token0'],'tokenB':row['token1'],'fee':row['fee']}
                    async with self.database.connection() as connection:
                        await connection.execute('''INSERT INTO quote_pool_identity_cache
                            (chain_id,dex,identity,token0,token1,fee,identifier,last_checked_at)
                            VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s)
                            ON CONFLICT(chain_id,dex,identity) DO UPDATE SET
                            identifier=EXCLUDED.identifier,last_checked_at=EXCLUDED.last_checked_at''',
                            (self.producer.chain_id,row['dex'],self.identity(identifier),row['token0'],row['token1'],
                             row['fee'],json.dumps(identifier),row['context']['observedAt']))
                    if row['protocol'] != 'v3':
                        continue
                async with self.database.connection() as connection:
                    # Replace the complete observation. OR/COALESCE would keep
                    # historical fabricated addresses/existence/liquidity.
                    # Quote-success hints have no authority; current route
                    # selection does not use this field beyond cache hydration.
                    await connection.execute('''INSERT INTO quote_pool_cache(chain_id,dex,token0,token1,fee,
                        pool_address,exists,success_count,active_liquidity_raw,sqrt_price_x96_raw,tick,
                        token0_balance_raw,token1_balance_raw,liquidity_checked_at,last_checked_at)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,0,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT(chain_id,dex,token0,token1,fee) DO UPDATE SET
                        pool_address=EXCLUDED.pool_address,exists=EXCLUDED.exists,success_count=0,
                        active_liquidity_raw=EXCLUDED.active_liquidity_raw,
                        sqrt_price_x96_raw=EXCLUDED.sqrt_price_x96_raw,tick=EXCLUDED.tick,
                        token0_balance_raw=EXCLUDED.token0_balance_raw,token1_balance_raw=EXCLUDED.token1_balance_raw,
                        liquidity_checked_at=EXCLUDED.liquidity_checked_at,last_checked_at=EXCLUDED.last_checked_at,
                        last_success_at=NULL,updated_at=NOW()''',
                        (self.producer.chain_id, row['dex'], row['token0'], row['token1'], row['fee'],
                         row.get('poolAddress'), row['exists'], row.get('activeLiquidityRaw'),
                         row.get('sqrtPriceX96Raw'), row.get('tick'), row.get('token0BalanceRaw'),
                         row.get('token1BalanceRaw'), row['context']['observedAt'] if row['exists'] else None,
                         row['context']['observedAt']))
