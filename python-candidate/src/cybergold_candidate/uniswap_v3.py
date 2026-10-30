"""Optional V3 bitmap acquisition; the SDK still performs every swap step."""
from web3 import Web3

from .finalized_multicall import ADDRESS


def empty_traversal_words(snapshot, requests, words):
    spacing = int(snapshot['tickSpacing'])
    current = (int(snapshot['tick']) // spacing) >> 8
    lower, upper = (-887272 // spacing) >> 8, (887272 // spacing) >> 8
    positions = set()
    for request in requests:
        direction = request.get('zeroForOne')
        if type(direction) is not bool or request.get('activeLiquidity') != '0':
            continue
        step = -1 if direction else 1
        for word in request.get('wordPositions', []):
            word = int(word)
            if word == current or int(words[word]['bitmap']):
                continue
            positions.update(position for offset in range(1, 32)
                             if lower <= (position := word + step * offset) <= upper)
    return sorted(positions - words.keys())


async def read_bitmap_words(read_function, address, positions, block):
    codec = Web3().codec
    selector = Web3.keccak(text='tickBitmap(int16)')[:4]
    result = []
    for index in range(0, len(positions), 31):
        batch = positions[index:index + 31]
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
