// The retained writer runs only against native_recovery_db.py's disposable DB.
import {Pool} from 'pg';
import {readRecoveryShareV2Checkpoint,reconcileRecoveryShareBalancesV2}
  from '../../src/server/onchain-indexer/recoverySharePersistence';
const pool=new Pool({connectionString:process.env.DATABASE_URL});
const client=await pool.connect();
const config={chainId:31338n,coreAddress:'0x0000000000000000000000000000000000000003' as const};
const runQuery=(sql:string,params?:unknown[])=>client.query(sql,params);
try{
  let result=null;
  if(process.env.FIXTURE_APPLY==='1'){
    await client.query('BEGIN');
    result=await reconcileRecoveryShareBalancesV2({config,snapshotBlock:102n,
      snapshotBlockHash:('0x'+'c'.repeat(64)) as `0x${string}`,profile:'fixture-profile',
      canonicalPreviousCheckpointHash:('0x'+'b'.repeat(64)) as `0x${string}`,transactionQuery:runQuery});
    await client.query('COMMIT');
  }
  const checkpoint=await readRecoveryShareV2Checkpoint(config,runQuery);
  const balances=(await client.query(`SELECT share_id,holder_address,balance_raw
    FROM onchain_recovery_share_balances_v2 WHERE chain_id=31338 AND contract_address=$1
    ORDER BY holder_address,share_id::numeric`,[config.coreAddress])).rows;
  console.log(JSON.stringify({result,checkpoint,balances},(_key,value)=>typeof value==='bigint'?value.toString():value));
}finally{client.release();await pool.end();}
