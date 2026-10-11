"""Retained signed-alias message, signature, nonce and SQL domains."""
import json
import math
import re

from eth_account.messages import defunct_hash_message
from eth_keys import keys

from .retained_reads import date_wire

JS_WHITESPACE = '\u0009\u000a\u000b\u000c\u000d\u0020\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff'


class AliasAuthError(Exception):
    pass


def alias_message(params):
    payload = {'action':params['action'], 'editorAddress':params['editorAddress'].lower(),
               'ownerAddress':params['ownerAddress'].lower(), 'alias':params['alias'].strip(JS_WHITESPACE),
               'nonce':params['nonce'], 'issuedAt':params['issuedAt']}
    encoded = json.dumps(payload, separators=(',', ':'), ensure_ascii=False)
    # JSON.stringify emits well-formed JSON for lone UTF-16 surrogates.
    encoded = re.sub(r'[\ud800-\udfff]', lambda match:'\\u'+format(ord(match[0]),'04x'), encoded)
    return 'CyberGold governance owner alias authorization\n' + encoded


def verify_alias_signature(params, issued_at_ms, now_ms):
    # The service parses issuedAt with the retained V8 date-string semantics;
    # parsed timestamps are never accepted from a client.
    if not math.isfinite(issued_at_ms):
        raise AliasAuthError('Invalid alias authorization timestamp.')
    if issued_at_ms > now_ms + 30_000:
        raise AliasAuthError('Alias authorization timestamp is in the future.')
    if now_ms - issued_at_ms > 300_000:
        raise AliasAuthError('Alias authorization expired. Please sign again.')
    try:
        signature = bytes.fromhex(params['signature'][2:])
        # Viem accepts 65-byte signatures with parity 0/1 or v=27/28. Normalize
        # that existing encoding for eth_keys' native length/parity checks.
        # Account.recover_message additionally accepts EIP-155 v, which would
        # silently broaden the current message-signature authorization.
        if len(signature) == 64:
            # EIP-2098 stores yParity in the high bit of s. Unpack that
            # representation; standard eth_keys still verifies and recovers.
            parity_and_s = int.from_bytes(signature[32:], 'big')
            normalized = (signature[:32] + (parity_and_s & ((1 << 255) - 1)).to_bytes(32, 'big')
                          + bytes([parity_and_s >> 255]))
        else:
            v = signature[-1]
            normalized = signature[:-1] + bytes([v-27 if v>=27 else v])
        recovered = keys.Signature(signature_bytes=normalized).recover_public_key_from_msg_hash(
            defunct_hash_message(text=alias_message(params))).to_checksum_address()
    except Exception:
        raise AliasAuthError('Invalid alias authorization signature.') from None
    if recovered.lower() != params['editorAddress'].lower():
        raise AliasAuthError('Alias authorization signer does not match editor address.')


async def verify_and_consume(pool, params, issued_at_ms, now_ms):
    verify_alias_signature(params, issued_at_ms, now_ms)
    await consume_nonce(pool, params)


async def consume_nonce(pool, params, connection=None):
    if connection is None:
        async with pool.connection() as connection:
            return await consume_nonce(pool, params, connection)
    cursor = await connection.execute('''
        INSERT INTO governance_owner_alias_auth_nonces(editor_address,nonce,used_at)
        VALUES (%s,%s,NOW()) ON CONFLICT DO NOTHING RETURNING 1 AS inserted
    ''', (params['editorAddress'].lower(),params['nonce']))
    if await cursor.fetchone() is None:
        raise AliasAuthError('Alias authorization nonce has already been used.')


class AliasService:
    def __init__(self,database,now_ms=None):
        import time
        self.database=database
        self.now_ms=now_ms or (lambda:time.time_ns()//1_000_000)

    async def authorize(self,params):
        from .alias_dates import date_milliseconds
        verify_alias_signature(params,date_milliseconds(params['issuedAt']),self.now_ms())
        await self.database.ensure_schema()
        await consume_nonce(self.database,params)

    async def mutate(self,params):
        from .alias_dates import date_milliseconds
        verify_alias_signature(params,date_milliseconds(params['issuedAt']),self.now_ms())
        await self.database.ensure_schema()
        async with self.database.connection() as connection:
            async with connection.transaction():
                await consume_nonce(self.database,params,connection)
                if params['action']=='upsert':
                    return await upsert_alias(self.database,params['editorAddress'],params['ownerAddress'],
                                              params['alias'],connection)
                return await delete_alias(self.database,params['editorAddress'],params['ownerAddress'],connection)

    async def list(self,editor,owners):
        await self.database.ensure_schema()
        return await list_aliases(self.database,editor,owners)

    async def upsert(self,editor,owner,alias):
        await self.database.ensure_schema()
        return await upsert_alias(self.database,editor,owner,alias)

    async def delete(self,editor,owner):
        await self.database.ensure_schema()
        return await delete_alias(self.database,editor,owner)


def alias_row(row):
    return {'editorAddress':row['editor_address'].lower(),'ownerAddress':row['owner_address'].lower(),
            'alias':row['alias'],'updatedAt':date_wire(row['updated_at'])}


async def list_aliases(pool, editor, owners):
    normalized = list(dict.fromkeys(owner.lower() for owner in owners))
    if not normalized:
        return []
    async with pool.connection() as connection:
        cursor = await connection.execute('''SELECT editor_address,owner_address,alias,updated_at
            FROM governance_owner_aliases WHERE editor_address=%s AND owner_address=ANY(%s::text[])
            ORDER BY owner_address ASC''', (editor.lower(),normalized))
        return [alias_row(row) for row in await cursor.fetchall()]


async def upsert_alias(pool, editor, owner, alias, connection=None):
    if connection is None:
        async with pool.connection() as connection:
            return await upsert_alias(pool,editor,owner,alias,connection)
    cursor = await connection.execute('''INSERT INTO governance_owner_aliases(editor_address,owner_address,alias,updated_at)
        VALUES (%s,%s,%s,NOW()) ON CONFLICT(editor_address,owner_address)
        DO UPDATE SET alias=EXCLUDED.alias,updated_at=NOW()
        RETURNING editor_address,owner_address,alias,updated_at''', (editor.lower(),owner.lower(),alias))
    row = await cursor.fetchone()
    if row is None:
        raise RuntimeError('Failed to save governance owner alias.')
    return alias_row(row)


async def delete_alias(pool, editor, owner, connection=None):
    if connection is None:
        async with pool.connection() as connection:
            return await delete_alias(pool,editor,owner,connection)
    cursor = await connection.execute('''DELETE FROM governance_owner_aliases
        WHERE editor_address=%s AND owner_address=%s RETURNING 1 AS deleted''', (editor.lower(),owner.lower()))
    return await cursor.fetchone() is not None
