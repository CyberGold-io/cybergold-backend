"""Shared directional bitmap acquisition policy and V3 transport.

The SDK still performs every swap step. Coverage only brings observed bitmap
words forward; it never treats an empty region as global liquidity exhaustion.
"""
from web3 import Web3

from .finalized_multicall import ADDRESS


def empty_traversal_words(snapshot, requests, words):
    spacing = int(snapshot['tickSpacing'])
    current = (int(snapshot['tick']) // spacing) >> 8
    lower, upper = (-887272 // spacing) >> 8, (887272 // spacing) >> 8
    positions, known = [], set(words)
    for request in requests:
        direction = request.get('zeroForOne')
        if type(direction) is not bool or request.get('activeLiquidity') != '0':
            continue
        step = -1 if direction else 1
        for word in request.get('wordPositions', []):
            word = int(word)
            if word == current or int(words[word]['bitmap']):
                continue
            # Start with the existing 31 upcoming words. A long empty region
            # can otherwise require hundreds of SDK/RPC continuations from an
            # exhausted price boundary. Grow only after contiguous bitmap
            # coverage behind this demand has already proved empty.
            empty = 0
            traversed = min(96, abs(word - current) + 1)
            while empty < traversed:
                previous = words.get(word - step * empty)
                if previous is None or int(previous['bitmap']):
                    break
                empty += 1
            upcoming = 127 if empty >= 96 else 63 if empty >= 32 else 31
            for offset in range(1, upcoming + 1):
                position = word + step * offset
                if lower <= position <= upper and position not in known:
                    positions.append(position)
                    known.add(position)
    return positions


async def read_bitmap_words(read_function, address, positions, block):
    codec = Web3().codec
    selector = Web3.keccak(text='tickBitmap(int16)')[:4]
    result = []
    for index in range(0, len(positions), 127):
        batch = positions[index:index + 127]
        calls = [(address, True, selector + codec.encode(['int16'], [position])) for position in batch]
        rows, = await read_function(ADDRESS, 'aggregate3((address,bool,bytes)[])',
            ['(address,bool,bytes)[]'], [calls], ['(bool,bytes)[]'], block)
        for position, (success, raw) in zip(batch, rows, strict=True):
            if success:
                try:
                    bitmap, = codec.decode(['uint256'], raw)
                except Exception:
                    continue  # A failed optional word remains ordinarily demandable.
                result.append({'wordPosition': position, 'bitmap': str(bitmap)})
    return result
