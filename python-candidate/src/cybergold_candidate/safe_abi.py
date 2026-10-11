"""Preserve the retained Safe indexed/non-indexed execution log interpretation."""
import re

from web3 import Web3
from eth_abi.exceptions import DecodingError

CODEC = Web3().codec


def safe_execution_args(log):
    try:
        topics, data = log['topics'], log['data']
        if len(topics) >= 2 and re.fullmatch(r'0x[a-fA-F0-9]{64}', topics[1]):
            payment = 0 if data == '0x' else CODEC.decode(['uint256'], bytes.fromhex(data[2:]))[0]
            return {'safeTxHash': topics[1].lower(), 'payment': str(payment)}
        if len(data) >= 130:
            tx_hash, payment = CODEC.decode(['bytes32', 'uint256'], bytes.fromhex(data[2:]))
            return {'safeTxHash': '0x' + tx_hash.hex(), 'payment': str(payment)}
    except (KeyError, TypeError, ValueError, IndexError, DecodingError):
        return None
    return None
