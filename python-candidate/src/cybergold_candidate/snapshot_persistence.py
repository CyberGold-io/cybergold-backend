"""Retained model keys and four-snapshot retention within the worker transaction."""
import json

DASHBOARD_MODEL = 'onchain-dashboard-v1'
RECOVERY_MODEL = 'recovery-portfolio-v5'


async def persist_snapshot(connection, chain_id, address, model_key, block_number, payload):
    parameters = (str(chain_id),address.lower(),model_key,str(block_number))
    await connection.execute('''INSERT INTO onchain_read_model_snapshots(chain_id,contract_address,
        model_key,block_number,payload) VALUES (%s,%s,%s,%s,%s::jsonb)
        ON CONFLICT(chain_id,contract_address,model_key,block_number)
        DO UPDATE SET payload=EXCLUDED.payload,created_at=NOW()''',
        (*parameters,json.dumps(payload,separators=(',',':'),ensure_ascii=False)))
    await connection.execute('''DELETE FROM onchain_read_model_snapshots WHERE chain_id=%s
        AND contract_address=%s AND model_key=%s AND block_number>%s''',parameters)
    await connection.execute('''DELETE FROM onchain_read_model_snapshots WHERE chain_id=%s
        AND contract_address=%s AND model_key=%s AND block_number NOT IN (
        SELECT block_number FROM onchain_read_model_snapshots WHERE chain_id=%s
        AND contract_address=%s AND model_key=%s ORDER BY block_number DESC LIMIT 4)''',
        parameters[:3]*2)
