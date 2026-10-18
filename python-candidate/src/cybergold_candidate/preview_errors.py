"""Specific quote failures from the already-paid Core/Helpers revert bytes."""
from web3 import Web3


class KnownPreviewError(ValueError):
    def __init__(self, code, message, *, constraint=None):
        super().__init__(message)
        self.code = code
        self.constraint = constraint


ERRORS = {
    Web3.to_hex(Web3.keccak(text=signature))[:10]: (types, code, message)
    for signature, types, code, message in (
        ('InsufficientSupply()', [], 'insufficient-protocol-supply',
         'The redemption exceeds available CYGLD supply or redeemable collateral reserves.'),
        ('MaxTotalSupplyExceeded(uint256,uint256,uint256)', ['uint256'] * 3, 'issuance-cap-exceeded',
         'The issuance amount exceeds the CYGLD supply limit.'),
        ('CygldSupplyCapExceeded(uint256,uint256,uint256)', ['uint256'] * 3, 'issuance-cap-exceeded',
         'The issuance amount exceeds the CYGLD supply limit.'),
    )
}


def preview_error(error, *, mode=None, arguments=None):
    """Decode known ABI errors only; never expose provider diagnostics."""
    data = error.get('data')
    if not isinstance(data, str):
        return None
    match = ERRORS.get(data[:10].lower())
    if match is None:
        return None
    types, code, message = match
    try:
        values = Web3().codec.decode(types, bytes.fromhex(data[10:]))
    except Exception:
        # Invalid/unknown return bytes retain ordinary unavailable behavior.
        return None
    constraint = None
    if code == 'issuance-cap-exceeded':
        current, requested, limit = values
        maximum = Web3.to_hex(Web3.keccak(text='MaxTotalSupplyExceeded(uint256,uint256,uint256)'))[:10]
        constraint = {'kind': 'issuance-cap', 'quantity': 'gross-cygld-mint',
                      'limitKind': 'maximum-total-supply' if data[:10].lower() == maximum else 'effective-supply-cap',
                      'requestedRaw': str(requested), 'availableRaw': str(max(0, limit-current)),
                      'currentSupplyRaw': str(current), 'limitRaw': str(limit)}
    elif code == 'insufficient-protocol-supply' and isinstance(mode, str) and mode.startswith('redeem-'):
        # Core reuses InsufficientSupply for total-supply and reserve-minimum
        # failures. Only the focused exact-input method disambiguates it.
        if mode.endswith('-exact-in'):
            code = 'redemption-supply-exceeded'
            message = 'The CYGLD redemption input exceeds the available protocol supply after Helpers fees.'
            constraint = {'kind': 'redemption-supply', 'quantity': 'gross-cygld-input'}
            arguments = arguments if isinstance(arguments, dict) else {}
            params = arguments.get('params', arguments)
            requested = params.get('grossCygldIn') if isinstance(params, dict) else None
            if isinstance(requested, int) and 0 <= requested < 2**256:
                constraint['requestedRaw'] = str(requested)
        elif mode.endswith('-exact-out'):
            code = 'redemption-capacity-exceeded'
            message = 'The redemption output minimum exceeds redeemable collateral reserves or the available CYGLD supply.'
            constraint = {'kind': 'redemption-capacity', 'quantity': 'core-output-minima'}
    return KnownPreviewError(code, message, constraint=constraint)
