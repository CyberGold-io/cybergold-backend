"""ERC-1155 replay and incremental V2 PostgreSQL checkpoint."""
import math
import re

from .aliases import JS_WHITESPACE
from .indexer_policy import HASH

STATE_KEYS=['recovery_share_v2_version','recovery_share_v2_block','recovery_share_v2_block_hash','recovery_share_v2_profile']
ZERO='0x'+'0'*40
MAX_ROWS=100000


def parse_integer(value):
    if type(value) is int:return value
    if type(value) is float:
        return int(value) if math.isfinite(value) and value==int(value) else None
    if not isinstance(value,str):return None
    value=value.strip(JS_WHITESPACE)
    if value=='':return 0
    if re.fullmatch(r'[+-]?[0-9]+',value):return int(value)
    if re.fullmatch(r'0[xX][0-9a-fA-F]+|0[oO][0-7]+|0[bB][01]+',value):return int(value,0)
    return None


def parse_address(value):return value.lower() if isinstance(value,str) and re.fullmatch(r'0x[a-fA-F0-9]{40}',value) else None


def transfer(event_name,payload):
    args=payload.get('args') if isinstance(payload,dict) else None
    if not isinstance(args,dict):return None
    operator,from_address,to=(parse_address(args.get(key)) for key in ('operator','from','to'))
    if not operator or not from_address or not to:return None
    if event_name=='TransferSingle':ids=[parse_integer(args.get('id'))];amounts=[parse_integer(args.get('value'))]
    elif event_name=='TransferBatch':
        if not isinstance(args.get('ids'),list) or not isinstance(args.get('values'),list):return None
        ids=[parse_integer(value) for value in args['ids']];amounts=[parse_integer(value) for value in args['values']]
    else:return None
    if None in ids or None in amounts:return None
    return {'operator':operator,'from':from_address,'to':to,'ids':ids,'amounts':amounts}


def apply_transfer(balances,value):
    if len(value['ids'])!=len(value['amounts']):raise ValueError('Malformed ERC-1155 recovery-share transfer vector')
    from_address=value['from'].lower();to=value['to'].lower()
    for share_id,amount in zip(value['ids'],value['amounts'],strict=True):
        if amount==0:continue
        if share_id<=0 or share_id>=2**160 or amount<0:raise ValueError('Invalid ERC-1155 recovery-share transfer')
        if from_address==to:continue
        if from_address!=ZERO:
            key=f'{from_address}:{share_id}';remaining=balances.get(key,0)-amount
            if remaining<0:raise ValueError('ERC-1155 recovery-share replay underflow')
            if remaining==0:balances.pop(key,None)
            else:balances[key]=remaining
        if to!=ZERO:
            key=f'{to}:{share_id}';balances[key]=balances.get(key,0)+amount


def checkpoint_rows(rows):
    if not rows:return None
    if len(rows)!=4:raise ValueError('Recovery-share v2 checkpoint is incomplete')
    values={}
    for row in rows:
        key=row['state_key'];value=row['state_value']
        if key not in STATE_KEYS or not isinstance(value,str) or key in values:
            raise ValueError('Recovery-share v2 checkpoint is ambiguous')
        values[key]=value
    version,block,block_hash,profile=(values.get(key) for key in STATE_KEYS)
    if not version or not block or not re.fullmatch(r'(0|[1-9][0-9]*)',block) or not block_hash or not HASH.fullmatch(block_hash) or not profile:
        raise ValueError('Recovery-share v2 checkpoint is invalid')
    return {'version':version,'blockNumber':int(block),'blockHash':block_hash.lower(),'profile':profile}


async def read_checkpoint(connection,chain_id,core,for_update=False):
    cursor=await connection.execute('''SELECT state_key,state_value FROM onchain_sync_state
        WHERE chain_id=%s AND contract_address=%s AND state_key=ANY(%s::text[])'''+(' FOR UPDATE' if for_update else ''),
        (str(chain_id),core.lower(),STATE_KEYS))
    return checkpoint_rows(await cursor.fetchall())


async def reconcile_v2(connection,chain_id,core,snapshot_block,snapshot_hash,profile,canonical_previous_hash):
    checkpoint=await read_checkpoint(connection,chain_id,core,True)
    if checkpoint and checkpoint['blockNumber']>snapshot_block:raise ValueError('Recovery-share v2 checkpoint is ahead of the snapshot')
    if checkpoint and checkpoint['blockNumber']==snapshot_block and checkpoint['blockHash'].lower()!=snapshot_hash.lower():
        raise ValueError('Recovery-share v2 snapshot hash changed')
    if checkpoint and checkpoint['version']=='1' and checkpoint['profile']==profile and checkpoint['blockNumber']==snapshot_block:
        return {'rebuilt':False,'appliedLogCount':0}
    incremental=bool(checkpoint and checkpoint['version']=='1' and checkpoint['profile']==profile
        and checkpoint['blockNumber']<snapshot_block and canonical_previous_hash
        and checkpoint['blockHash'].lower()==canonical_previous_hash.lower())
    lower=checkpoint['blockNumber'] if incremental else None
    parameters=[str(chain_id),core.lower(),str(snapshot_block)]+([str(lower)] if lower is not None else [])
    cursor=await connection.execute('''SELECT event_name,payload FROM onchain_event_logs
        WHERE chain_id=%s AND contract_address=%s AND event_name IN ('TransferSingle','TransferBatch')
        AND block_number<=%s'''+(' AND block_number>%s' if lower is not None else '')+'''
        ORDER BY block_number ASC,log_index ASC,tx_hash ASC LIMIT 100001''',parameters)
    logs=await cursor.fetchall()
    if len(logs)>MAX_ROWS:raise ValueError('Recovery-share v2 replay exceeds 100000 indexed transfer logs')
    balances={}
    if incremental:
        cursor=await connection.execute('''SELECT share_id,holder_address,balance_raw FROM onchain_recovery_share_balances_v2
            WHERE chain_id=%s AND contract_address=%s ORDER BY share_id::numeric ASC,holder_address ASC LIMIT 100001''',
            (str(chain_id),core.lower()))
        rows=await cursor.fetchall()
        if len(rows)>MAX_ROWS:raise ValueError('Recovery-share v2 balance cardinality limit exceeded')
        for row in rows:
            holder=parse_address(row['holder_address']);share_id=parse_integer(row['share_id']);balance=parse_integer(row['balance_raw'])
            if not holder or share_id is None or balance is None or balance<=0:
                raise ValueError('Stored recovery-share v2 balance is invalid')
            balances[f'{holder}:{share_id}']=balance
    for row in logs:
        value=transfer(row['event_name'],row['payload'])
        if value is None:raise ValueError('Malformed indexed ERC-1155 '+row['event_name']+' payload')
        apply_transfer(balances,value)
        if len(balances)>MAX_ROWS:raise ValueError('Recovery-share v2 balance cardinality limit exceeded')
    await connection.execute('DELETE FROM onchain_recovery_share_balances_v2 WHERE chain_id=%s AND contract_address=%s',
        (str(chain_id),core.lower()))
    for key,balance in sorted(balances.items()):
        holder,share_id=key.rsplit(':',1)
        await connection.execute('''INSERT INTO onchain_recovery_share_balances_v2
            (chain_id,contract_address,share_id,holder_address,balance_raw) VALUES(%s,%s,%s,%s,%s)''',
            (str(chain_id),core.lower(),share_id,holder,str(balance)))
    for key,value in zip(STATE_KEYS,['1',str(snapshot_block),snapshot_hash.lower(),profile],strict=True):
        await connection.execute('''INSERT INTO onchain_sync_state(chain_id,contract_address,state_key,state_value)
            VALUES(%s,%s,%s,%s) ON CONFLICT(chain_id,contract_address,state_key)
            DO UPDATE SET state_value=EXCLUDED.state_value,updated_at=NOW()''',(str(chain_id),core.lower(),key,value))
    return {'rebuilt':not incremental,'appliedLogCount':len(logs)}
