"""Canonical App timestamps and normalized signatures retain message/replay semantics."""
import asyncio
from contextlib import asynccontextmanager
import unittest
from unittest.mock import patch
from eth_account import Account
from eth_account.messages import encode_defunct
from cybergold_candidate.alias_dates import date_milliseconds
from cybergold_candidate.aliases import AliasService, AliasAuthError, alias_message

KEY = bytes.fromhex('11' * 32)  # Synthetic fixture key, no chain operation.
NOW = 1790762400000


class Database:
    def __init__(self): self.used = set(); self.pending = None
    async def ensure_schema(self): pass
    @asynccontextmanager
    async def connection(self): yield self
    async def execute(self, _sql, params): self.pending = params; return self
    async def fetchone(self):
        if self.pending in self.used: return None
        self.used.add(self.pending); return {'inserted': 1}


def payload(nonce='fixture'):
    params = {'action':'upsert','editorAddress':Account.from_key(KEY).address,
              'ownerAddress':'0x'+'a'*40,'alias':'Alias 😀','nonce':nonce,
              'issuedAt':'2026-09-30T10:00:00.000Z'}
    signature = Account.sign_message(encode_defunct(text=alias_message(params)), KEY).signature
    compact = signature[:32] + (int.from_bytes(signature[32:64],'big') | ((signature[64]-27) << 255)).to_bytes(32,'big')
    return params, '0x'+signature.hex(), '0x'+compact.hex()


class CanonicalTests(unittest.IsolatedAsyncioTestCase):
    async def test_apps_iso_timestamp_uses_native_parser_without_legacy_interpreter(self):
        with patch('cybergold_candidate.alias_dates.legacy_date_milliseconds',side_effect=AssertionError('Legacy parser used')):
            self.assertEqual(date_milliseconds('2026-09-30T10:00:00.000Z'), NOW)
            self.assertEqual(date_milliseconds('1969-12-31T23:59:59.999Z'), -1)

    async def test_compact_and_standard_encoding_share_one_consumed_nonce(self):
        params, standard, compact = payload()
        for first, second in ((compact,standard),(standard,compact)):
            db = Database(); reader = AliasService(db,lambda:NOW)
            await reader.authorize({**params,'signature':first})
            with self.assertRaisesRegex(AliasAuthError,'nonce has already been used'):
                await reader.authorize({**params,'signature':second})
            self.assertEqual(len(db.used),1)

    async def test_tampering_never_consumes_nonce_and_raw_timestamp_remains_signed(self):
        params, _standard, compact = payload(); db = Database(); reader = AliasService(db,lambda:NOW)
        for change in ({'alias':'tampered'},{'issuedAt':'2026-09-30T10:00:00Z'}):
            with self.assertRaisesRegex(AliasAuthError,'signer does not match'):
                await reader.authorize({**params,**change,'signature':compact})
        self.assertEqual(db.used,set())

    async def test_compact_signatures_preserve_expiry_and_skew_boundaries(self):
        params, _standard, compact = payload()
        for delta, error in ((300001,'expired'),(-30001,'future')):
            db = Database(); reader = AliasService(db,lambda:NOW+delta)
            with self.assertRaisesRegex(AliasAuthError,error):
                await reader.authorize({**params,'signature':compact})
            self.assertEqual(db.used,set())


if __name__=='__main__': unittest.main()
