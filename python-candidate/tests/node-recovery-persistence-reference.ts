import {parseBigIntLike,parseAddressLike,extractRecoveryShareTransferArgs,readRecoveryShareV2Checkpoint}
  from '../../src/server/onchain-indexer/recoverySharePersistence';
import {applyIndexedRecoveryShareTransfer} from '../../src/utils/recovery';
const zero='0x'+'0'.repeat(40),a='0x'+'a'.repeat(40),b='0x'+'b'.repeat(40),hash='0x'+'c'.repeat(64);
const cases:any[]=[];const add=(op:string,input:any)=>cases.push({op,input});
for(const value of [null,true,0,1,-1,1.5,9007199254740992,0n,2n**256n-1n,'','  ','01','-1','+1',
 '0x12','-0x12','0b11','0o12','1e2','garbage'])add('integer',value);
for(const value of [null,true,a,a.toUpperCase().replace('0X','0x'),a.slice(2),'0xaa'])add('address',value);
const args={operator:a,from:zero,to:b,id:'1',value:'9007199254740993'};
for(const event of ['TransferSingle','TransferBatch','unknown'])for(const payload of [null,{}, {args},
 {args:{...args,ids:['1','2'],values:['3','4']}},{args:{...args,operator:'bad'}},
 {args:{...args,id:null}},{args:{...args,ids:['1'],values:[true]}}])add('transfer',{event,payload});
for(const amount of [-1n,0n,1n,2n**256n-1n])for(const id of [0n,1n,2n**160n])for(const same of [false,true])
 add('apply',{balances:[],value:{operator:a,from:zero,to:same?zero:b,ids:[id],amounts:[amount]}});
add('apply',{balances:[[a+':1',5n]],value:{operator:a,from:a,to:b,ids:[1n],amounts:[5n]}});
add('apply',{balances:[[a+':1',5n]],value:{operator:a,from:a,to:b,ids:[1n],amounts:[6n]}});
add('apply',{balances:[],value:{operator:a,from:a,to:b,ids:[1n,2n],amounts:[1n]}});
const rows=[{state_key:'recovery_share_v2_version',state_value:'1'}, {state_key:'recovery_share_v2_block',state_value:'100'},
 {state_key:'recovery_share_v2_block_hash',state_value:hash},{state_key:'recovery_share_v2_profile',state_value:'profile'}];
for(const value of [[],rows,rows.slice(1),[rows[0],rows[0],rows[2],rows[3]],
 ...[0,1,2,3].flatMap(index=>['',null,'01'].map(state_value=>rows.map((row,i)=>i===index?{...row,state_value}:row)))])add('checkpoint',value);
for(const entry of cases){let result:any=null,error:string|null=null;
 try{const value=entry.input;switch(entry.op){
 case 'integer':result=parseBigIntLike(value);break;
 case 'address':result=parseAddressLike(value);break;
 case 'transfer':result=extractRecoveryShareTransferArgs(value.event,value.payload);break;
 case 'apply':{const balances=new Map<string,bigint>(value.balances);applyIndexedRecoveryShareTransfer(balances,value.value);result=[...balances.entries()];break;}
 case 'checkpoint':result=await readRecoveryShareV2Checkpoint({chainId:31338n,coreAddress:a as any},async()=>({rows:value}));break;
 }}catch(failure){error=(failure as Error).message;}
 Object.assign(entry,{result,error});}
console.log(JSON.stringify(cases,(_key,value)=>typeof value==='bigint'?{$bigint:value.toString()}:value));
