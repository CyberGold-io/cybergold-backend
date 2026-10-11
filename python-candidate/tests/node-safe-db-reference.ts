// The DSN supplied by the fixture runner points only to its fresh local container.
import { ensureSchema, query, withTransaction } from "../../src/server/onchain-indexer/db";
import { selectSafeActivity } from "../../src/server/safe-events/activity";
import { selectCoreActivity } from "../../src/server/onchain-indexer/coreActivity";
import { toEventHash, encodeAbiParameters } from "viem";
import { readCachedDashboardSnapshot } from '../../src/server/onchain-indexer/dashboardSnapshotRepository';
import { listCachedPools } from '../../src/server/quote-pool-cache/repository';
import { listOwnerAliases } from '../../src/server/governance-owner-aliases/repository';
import { buildGovernanceOwnerAliasAuthMessage } from '../../src/utils/governanceOwnerAliasesAuth';
import { privateKeyToAccount } from 'viem/accounts';

const safe = "0x0000000000000000000000000000000000000001";
const other = "0x0000000000000000000000000000000000000002";
const core = "0x0000000000000000000000000000000000000003";
const hash = `0x${"a".repeat(64)}` as `0x${string}`;
const read = (chain = 31338, addresses = [safe, other]) => withTransaction(async execute => {
  await execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY");
  return selectSafeActivity(execute, chain, addresses, 50_000n);
});
try {
  await ensureSchema();
  await query(`INSERT INTO onchain_raw_logs(chain_id,contract_address,block_number,block_hash,
      tx_hash,log_index,block_timestamp_seconds,topics,data)
    VALUES (31338,$1,100,$3,$3,0,1000,$4::jsonb,$5),
           (31338,$2,101,$3,$3,1,1001,$6::jsonb,$7)`,
    [safe, other, hash, JSON.stringify([toEventHash("ExecutionSuccess(bytes32,uint256)")]),
      encodeAbiParameters([{type:"bytes32"},{type:"uint256"}], [hash, 2n**256n-1n]),
      JSON.stringify([toEventHash("ExecutionFailure(bytes32,uint256)"), hash]),
      encodeAbiParameters([{type:"uint256"}], [2n**64n])]);
  await query(`INSERT INTO onchain_sync_state(chain_id,contract_address,state_key,state_value)
    VALUES (31338,$1,'raw_log_start_block','90'),(31338,$1,'raw_log_last_scanned_block','60000'),
           (31338,$1,'safe_execution_last_scanned_block','60000')`, [safe]);
  const initial = await read();
  const separateChain = await read(1);
  const oneSafe = await read(31338, [other]);
  const noAddresses = await read(31338, []);
  await query(`INSERT INTO onchain_raw_logs(chain_id,contract_address,block_number,block_hash,
      tx_hash,log_index,block_timestamp_seconds,topics,data)
    VALUES (31338,$1,400,$2,$2,0,1000,$3::jsonb,'0x'),
           (31338,$1,401,$2,$2,1,1001,$4::jsonb,'0x'),
           (31338,$1,402,$2,$2,2,1002,'[]'::jsonb,'0x')`, [core,hash,
    JSON.stringify([toEventHash('Unpaused(address)'), '0x'+'0'.repeat(24)+'ab'.repeat(20)]),
    JSON.stringify([toEventHash('OwnershipTransferred(address,address)'), '0x'+'0'.repeat(24)+'ab'.repeat(20), '0x'+'0'.repeat(24)+'cd'.repeat(20)])]);
  await query(`INSERT INTO onchain_sync_state(chain_id,contract_address,state_key,state_value)
    VALUES (31338,$1,'raw_log_start_block','100'),(31338,$1,'raw_log_last_scanned_block','500'),
           (31338,$1,'raw_log_last_scanned_block_hash',$2)`,[core,hash]);
  const coreRead=(chain:number,address:string)=>withTransaction(async execute=>{
    await execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY');
    return selectCoreActivity(execute,chain,address);
  });
  const coreInitial=await coreRead(31338,core);
  const coreOtherChain=await coreRead(1,core);
  const coreOtherAddress=await coreRead(31338,'0x0000000000000000000000000000000000000004');
  const payload={enabled:true,lastScannedBlock:'499',supply:'115792089237316195423570985008687907853269984665640564039457584007913129639935',reserves:[{address:other,amount:'0'}]};
  await query(`INSERT INTO onchain_read_model_snapshots(chain_id,contract_address,model_key,block_number,payload)
    VALUES (31338,$1,'onchain-dashboard-v1',499,$2::jsonb),
           (31338,$1,'other-model',900,'{}'::jsonb),
           (1,$1,'onchain-dashboard-v1',100,'{"enabled":false}'::jsonb)`,[core,JSON.stringify(payload)]);
  const dashboard=await readCachedDashboardSnapshot({chainId:31338n,coreAddress:core});
  const otherDashboard=await readCachedDashboardSnapshot({chainId:1n,coreAddress:core});
  await query(`INSERT INTO quote_pool_cache(chain_id,dex,token0,token1,fee,pool_address,exists,success_count,
    active_liquidity_raw,sqrt_price_x96_raw,tick,token0_balance_raw,token1_balance_raw,liquidity_checked_at,last_checked_at)
    VALUES (31338,'uniswap_v3',$1,$2,500,$3,true,2,'9007199254740993','79228162514264337593543950336',-1,'0','2','2026-09-30T10:00:00Z',NOW()),
           (31338,'uniswap_v3',$1,$2,3000,NULL,false,0,NULL,NULL,NULL,NULL,NULL,NULL,NOW()),
           (31338,'uniswap_v3',$1,$2,10000,NULL,true,9,NULL,NULL,NULL,NULL,NULL,NULL,NOW()-interval '25 hours'),
           (1,'uniswap_v3',$1,$2,500,NULL,false,0,NULL,NULL,NULL,NULL,NULL,NULL,NOW())`,[safe,other,core]);
  const pairs=[{tokenA:other,tokenB:safe},{tokenA:safe,tokenB:other}];
  const pools=await listCachedPools({chainId:31338,dex:'uniswap_v3',pairs});
  const otherPools=await listCachedPools({chainId:1,dex:'uniswap_v3',pairs});
  const emptyPools=await listCachedPools({chainId:31338,dex:'uniswap_v3',pairs:[]});
  const account=privateKeyToAccount(('0x'+'1'.repeat(64)) as `0x${string}`);
  const editor=account.address.toLowerCase();
  await query(`INSERT INTO governance_owner_aliases(editor_address,owner_address,alias,updated_at)
    VALUES ($1,$2,'Treasury','2026-09-30T10:00:00Z'),($1,$3,'Second','2026-09-30T10:00:01Z'),
           ($3,$2,'Other editor','2026-09-30T10:00:00Z')`,[editor,safe,other]);
  const aliases=await listOwnerAliases({editorAddress:account.address,ownerAddresses:[other,safe,other]});
  const emptyAliases=await listOwnerAliases({editorAddress:account.address,ownerAddresses:[]});
  const params={action:'upsert',editorAddress:account.address,ownerAddress:safe,alias:'Python durable write',
    nonce:'durable-candidate-nonce',issuedAt:'2026-09-30T10:00:00.000Z'} as const;
  const signature=await account.signMessage({message:buildGovernanceOwnerAliasAuthMessage(params)});
  process.stdout.write(JSON.stringify({views:{initial,separateChain,oneSafe,noAddresses,coreInitial,coreOtherChain,coreOtherAddress,
    dashboard,otherDashboard,pools,otherPools,emptyPools,aliases,emptyAliases},aliasParams:{...params,signature}})+"\n");
} finally { await globalThis.__cybergoldDashboardPgPool?.end(); }
