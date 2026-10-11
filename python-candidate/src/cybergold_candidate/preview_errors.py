"""Specific quote failures from the already-paid Core/Helpers revert bytes."""
from web3 import Web3


class KnownPreviewError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


ERRORS = {
    Web3.to_hex(Web3.keccak(text=signature))[:10]: (types, code, message)
    for signature, types, code, message in (
        ('InsufficientSupply()', [], 'insufficient-protocol-supply',
         'The redemption amount exceeds available CYGLD supply.'),
        ('MaxTotalSupplyExceeded(uint256,uint256,uint256)', ['uint256'] * 3, 'issuance-cap-exceeded',
         'The issuance amount exceeds the CYGLD supply limit.'),
        ('CygldSupplyCapExceeded(uint256,uint256,uint256)', ['uint256'] * 3, 'issuance-cap-exceeded',
         'The issuance amount exceeds the CYGLD supply limit.'),
    )
}


def preview_error(error):
    """Decode known ABI errors only; never expose provider diagnostics."""
    data = error.get('data')
    if not isinstance(data, str):
        return None
    match = ERRORS.get(data[:10].lower())
    if match is None:
        return None
    types, code, message = match
    try:
        Web3().codec.decode(types, bytes.fromhex(data[10:]))
    except Exception:
        # Invalid/unknown return bytes retain ordinary unavailable behavior.
        return None
    return KnownPreviewError(code, message)
