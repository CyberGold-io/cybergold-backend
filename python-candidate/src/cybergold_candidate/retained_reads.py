"""Existing completed dashboard and pool-cache reads; no schema/data migration."""
from datetime import timezone


def disabled_dashboard():
    return {'enabled': False, 'protocolLogicUpdate': None, 'protocolParameterUpdate': None, 'lastScannedBlock': None}


def node_json_numbers(value):
    # pg's Node JSON parser reads JSON numbers as IEEE-754 Number. PostgreSQL
    # expands stored exponents; Python's JSON parser otherwise turns those
    # large integral metrics into exact integers and changes their wire value.
    # On-chain integer amounts already use decimal strings and stay unchanged.
    if type(value) is int and abs(value) > 2**53 - 1:
        return float(value)
    if isinstance(value, list):
        return [node_json_numbers(item) for item in value]
    if isinstance(value, dict):
        return {key: node_json_numbers(item) for key, item in value.items()}
    return value


async def dashboard_snapshot(pool, chain_id, core_address):
    if pool is None or not core_address:
        return disabled_dashboard()
    async with pool.connection() as connection:
        cursor = await connection.execute('''
            SELECT payload FROM onchain_read_model_snapshots
            WHERE chain_id=%s AND contract_address=%s AND model_key=%s
            ORDER BY block_number DESC LIMIT 1
        ''', (str(chain_id), core_address.lower(), 'onchain-dashboard-v1'))
        row = await cursor.fetchone()
        if row is None:
            raise RuntimeError('On-chain dashboard has no completed cached snapshot')
        return node_json_numbers(row['payload'])


def date_wire(value):
    return value.astimezone(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


async def cached_pools(pool, chain_id, dex, pairs):
    normalized = list(dict.fromkeys(tuple(sorted((pair['tokenA'].lower(), pair['tokenB'].lower()))) for pair in pairs))
    if not normalized:
        return []
    clauses = ' OR '.join('(token0=%s AND token1=%s)' for _ in normalized)
    parameters = (str(chain_id), dex, '24 hours', *(token for pair in normalized for token in pair))
    async with pool.connection() as connection:
        cursor = await connection.execute('''
            SELECT dex, token0, token1, fee, pool_address AS "poolAddress", exists,
                success_count AS "successCount", active_liquidity_raw AS "activeLiquidityRaw",
                sqrt_price_x96_raw AS "sqrtPriceX96Raw", tick,
                token0_balance_raw AS "token0BalanceRaw", token1_balance_raw AS "token1BalanceRaw",
                liquidity_checked_at AS "liquidityCheckedAt", last_checked_at AS "lastCheckedAt"
            FROM quote_pool_cache WHERE chain_id=%s AND dex=%s
                AND last_checked_at>=NOW()-%s::interval AND (''' + clauses + ''')
            ORDER BY exists DESC, success_count DESC, fee ASC
        ''', parameters)
        results = []
        for row in await cursor.fetchall():
            value = {key: row[key] for key in ('dex', 'token0', 'token1', 'fee', 'exists', 'successCount')}
            value['token0'], value['token1'] = value['token0'].lower(), value['token1'].lower()
            for key in ('poolAddress', 'activeLiquidityRaw', 'sqrtPriceX96Raw', 'tick', 'token0BalanceRaw',
                        'token1BalanceRaw', 'liquidityCheckedAt', 'lastCheckedAt'):
                if row[key] is not None:
                    value[key] = (date_wire(row[key]) if key.endswith('At') else
                                  row[key].lower() if key == 'poolAddress' else row[key])
            results.append(value)
        return results


async def cached_pool_identifiers(pool, chain_id, dex, pairs):
    """Identity hints only; the producer always obtains the public observation."""
    normalized = list(dict.fromkeys(tuple(sorted((pair['tokenA'].lower(), pair['tokenB'].lower()))) for pair in pairs))
    if not normalized:
        return []
    clauses = ' OR '.join('(token0=%s AND token1=%s)' for _ in normalized)
    dexes = ['uniswap_v2', 'uniswap_v3', 'uniswap_v4'] if dex == 'uniswap' else [dex]
    async with pool.connection() as connection:
        cursor = await connection.execute('''SELECT identifier FROM quote_pool_identity_cache
            WHERE chain_id=%s AND dex=ANY(%s) AND (''' + clauses + ''') ORDER BY dex,identity''',
            (chain_id, dexes, *(token for pair in normalized for token in pair)))
        return [row['identifier'] for row in await cursor.fetchall()]
