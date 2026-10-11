import {mock} from 'node:test';
import {parseCompactSignature,compactSignatureToSignature,serializeSignature} from 'viem';
import {privateKeyToAccount} from 'viem/accounts';
import {buildGovernanceOwnerAliasAuthMessage} from '../../src/utils/governanceOwnerAliasesAuth';
let calls:string[]=[];let used=false;
await mock.module(new URL('../../src/server/onchain-indexer/db.ts',import.meta.url).href,{exports:{
 ensureSchema:async()=>{calls.push('schema');},query:async()=>{calls.push('nonce');return {rows:used?[]:[{inserted:1}]};},
}});
const {verifyAndConsumeOwnerAliasWriteAuth}=await import('../../src/server/governance-owner-aliases/auth');
Date.now=()=>1790762400000;
const account=privateKeyToAccount('0x'+'1'.repeat(64) as `0x${string}`);
const values=['2026-09-30T10:00:00Z','2026-09-30T10:00:30Z','2026-09-30T10:00:30.001Z',
 '2026-09-30T09:55:00Z','2026-09-30T09:54:59.999Z','Wed, 30 Sep 2026 10:00:00 GMT',
 'Sep 30 2026 10:00 UTC','9/30/2026 10:00 GMT','garbage','2026-09-30T10:00:00Z trailing'];
const cases:any[]=[];
for(const issuedAt of values)for(const mode of ['normal','used','wrong-signature','compact']){
 used=mode==='used';calls=[];
 const params:any={action:'upsert',editorAddress:account.address,ownerAddress:'0x'+'a'.repeat(40),alias:'alias 😀',nonce:'fixture',issuedAt};
 params.signature=await account.signMessage({message:buildGovernanceOwnerAliasAuthMessage(params)});
 if(mode==='wrong-signature')params.alias='tampered';
 if(mode==='compact')params.signature=params.signature.slice(0,-2);
 let error=null;try{await verifyAndConsumeOwnerAliasWriteAuth({...params,signature:params.signature.length===130 ? serializeSignature(compactSignatureToSignature(parseCompactSignature(params.signature))) : params.signature});}catch(failure){error=(failure as Error).message;}
 cases.push({params,mode,error,calls});
}
console.log(JSON.stringify(cases));
