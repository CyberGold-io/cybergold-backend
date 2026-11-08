"""Explicit latest reads and retained pinned read parameters.

Zero is SDK-local construction metadata, never an observed block height.
"""
LATEST_BLOCK = {'number': 0, 'hash': 'latest', 'tag': 'latest'}


def is_latest(block):
    return block.get('tag') == 'latest'


def rpc_block_parameter(block):
    return 'latest' if is_latest(block) else {'blockHash': block['hash'], 'requireCanonical': True}
