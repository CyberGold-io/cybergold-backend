"""Retained Core/token/basket state reads and reference-price cache behavior."""
import asyncio
import json
from pathlib import Path
import time

from .recovery_persistence import parse_integer

ABI = json.loads(Path(__file__).with_name('indexer-state-abi.json').read_text())
REF_STATE = 'cygld_ref_grams_fp18'


def token_number(raw, decimals):
    whole, remainder = divmod(abs(raw), 10**decimals)
    return (-1 if raw < 0 else 1) * (float(whole) + float(remainder) / float(10**decimals))


class StateReads:
    def __init__(self, config, client, store, *, ref_ttl_ms=86400000, now_ms=None):
        self.config, self.client, self.store = config, client, store
        self.ref_ttl_ms = ref_ttl_ms or 86400000
        self.now_ms = now_ms or (lambda: time.time() * 1000)

    async def call(self, name, target, *, address=None, args=None):
        function = next(entry for entry in ABI if entry['name'] == name)
        request = {'address': address or self.config['coreAddress'], 'abi': [function], 'functionName': name, **target}
        if args is not None:
            request['args'] = args
        return await self.client.read_contract(request)

    async def core_metrics(self, target):
        names = ['totalSupply', 'decimals', 'issuanceFeePpm', 'redemptionFeePpm', 'paused']
        values = await asyncio.gather(*(self.call(name, target) for name in names))
        return dict(zip(['totalSupplyRaw', 'tokenDecimals', 'issuanceFeePpm', 'redemptionFeePpm', 'paused'], values, strict=True))

    async def reference_grams(self, target, *, force_pinned=False, terminal=None):
        cached = await self.store.state_entry(REF_STATE)
        value = (parse_integer(cached['stateValue']) or 0) if cached and cached.get('stateValue') else 0
        fresh = value > 0 and cached is not None and cached['updatedAtMs'] > 0 and self.now_ms() - cached['updatedAtMs'] < self.ref_ttl_ms
        if fresh and not force_pinned:
            return value
        try:
            current = await self.call('cygldRefGramsFp18', target)
            if not force_pinned:
                await self.store.put_state(REF_STATE, str(current))
            return current
        except Exception as error:
            if terminal is not None and terminal(error):
                raise
            if force_pinned:
                return None
            return value if value > 0 else None

    async def basket(self, target, *, force_pinned=False, terminal=None):
        async def safe(name, address=None, args=None):
            try:
                return await self.call(name, target, address=address, args=args)
            except Exception as error:
                if terminal is not None and terminal(error):
                    raise
                return None
        assets, targets, gold, units, reference = await asyncio.gather(
            safe('basketAssets'), safe('basketTargetsPpm'), safe('basketGoldRefGramsFp18'), safe('basketCygldPerUnitFp18'),
            self.reference_grams(target, force_pinned=force_pinned, terminal=terminal))
        if any(value is None for value in (assets, targets, gold, units)):
            return None
        reserve = self.config['coreAddress']
        result = {'reserveAddress': reserve.lower(), 'cygldRefGrams': None if reference is None else token_number(reference, 18),
            'cygldRefGramsFp18': None if reference is None else str(reference), 'assets': [], 'withinBand': None}
        if not assets or len(assets) != len(targets) or len(assets) != len(gold) or len(assets) != len(units):
            return result
        async def details(asset):
            balance, supply, decimals, symbol = await asyncio.gather(safe('balanceOf', asset, [reserve]),
                safe('totalSupply', asset), safe('decimals', asset), safe('symbol', asset))
            return {'balance': balance if balance is not None else 0, 'supply': supply,
                'decimals': decimals if decimals is not None else 18, 'symbol': symbol if symbol is not None else asset[:6] + '...' + asset[-4:]}
        rows = await asyncio.gather(*(details(asset) for asset in assets))
        values = [row['balance'] * units[index] // 10**18 for index, row in enumerate(rows)]
        total = sum(values)
        for index, asset in enumerate(assets):
            row = rows[index]
            actual = values[index] * 1000000 // total if total > 0 else 0
            drift = actual - targets[index]
            per_token = units[index] * 10**row['decimals'] // 10**18
            result['assets'].append({'address': asset.lower(), 'symbol': row['symbol'], 'targetPercent': float(targets[index]) / 10000,
                'actualPercent': float(actual) / 10000, 'driftPercent': float(drift) / 10000, 'decimals': row['decimals'],
                'reserveBalance': token_number(row['balance'], row['decimals']), 'reserveBalanceRaw': str(row['balance']),
                'totalSupply': None if row['supply'] is None else token_number(row['supply'], row['decimals']),
                'totalSupplyRaw': None if row['supply'] is None else str(row['supply']), 'goldRefGrams': token_number(gold[index], 18),
                'cygldPerUnitFp18': str(units[index]), 'cygldPerToken': token_number(per_token, 18)})
        result['withinBand'] = all(abs(asset['driftPercent']) <= 5 for asset in result['assets'])
        return result
