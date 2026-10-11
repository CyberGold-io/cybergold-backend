import json
from pathlib import Path
import sys

from eth_account.messages import defunct_hash_message

from cybergold_candidate.aliases import AliasAuthError, alias_message, verify_alias_signature


def main(path):
    cases = json.loads(Path(path).read_text())
    now_ms = 1790762400000
    for case in cases:
        params = case['params']
        message = alias_message(params)
        assert message == case['message'], (params['alias'], 'signed message bytes differ')
        assert '0x'+defunct_hash_message(text=message).hex() == case['hash']
        if case['error']:
            try: verify_alias_signature(params,now_ms,now_ms)
            except AliasAuthError as actual: assert str(actual)==case['error']
            else: raise AssertionError('Standard signature rejection changed')
            continue
        verify_alias_signature(params,now_ms,now_ms)
        for stamp,error in [(float('nan'),'Invalid alias authorization timestamp.'),
                            (now_ms+30001,'Alias authorization timestamp is in the future.'),
                            (now_ms-300001,'Alias authorization expired. Please sign again.')]:
            try: verify_alias_signature(params,stamp,now_ms)
            except AliasAuthError as actual: assert str(actual)==error
            else: raise AssertionError('Retained timestamp rule did not reject')
        verify_alias_signature(params,now_ms+30000,now_ms)
        verify_alias_signature(params,now_ms-300000,now_ms)
        try: verify_alias_signature({**params,'alias':'tampered'},now_ms,now_ms)
        except AliasAuthError as actual: assert str(actual)=='Alias authorization signer does not match editor address.'
        else: raise AssertionError('Tampered signed alias accepted')
    print(f'PASS: {len(cases)} actual Viem/eth-account message, EIP-191 hash and 64/65-byte signature comparisons; Unicode and existing time boundaries')


if __name__=='__main__':
    main(sys.argv[1])
