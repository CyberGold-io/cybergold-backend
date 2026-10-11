import {mock} from 'node:test';
let mode='normal';let calls:any[]=[];
class GovernanceOwnerAliasAuthError extends Error{}
await mock.module(new URL('../../src/server/governance-owner-aliases/auth.ts',import.meta.url).href,{exports:{
  GovernanceOwnerAliasAuthError,
  verifyAndConsumeOwnerAliasWriteAuth:async(input:any)=>{calls.push({operation:'authorize',input});
    if(mode==='auth-error')throw new GovernanceOwnerAliasAuthError('Alias authorization nonce has already been used.');},
}});
await mock.module(new URL('../../src/server/governance-owner-aliases/repository.ts',import.meta.url).href,{exports:{
  listOwnerAliases:async(input:any)=>{calls.push({operation:'list',input});if(mode==='db-error')throw new Error('private fixture');return [];},
  upsertOwnerAlias:async(input:any)=>{calls.push({operation:'upsert',input});return {fixture:'entry'};},
  deleteOwnerAlias:async(input:any)=>{calls.push({operation:'delete',input});return true;},
}});
const {POST}=await import('../../src/api/governance/owner-aliases/route');
const address='0x'+'a'.repeat(40);const auth={nonce:' nonce ',issuedAt:' 2026-09-30T10:00:00Z ',signature:'0x'+'1'.repeat(130)};
const base={action:'upsert',editorAddress:address,ownerAddress:address,alias:' alias ',auth};
const cases:any[]=[];
for(const body of [null,[],{},true,1,'text',{action:false},{action:[]},base,{...base,alias:'😀'.repeat(32)},
 {...base,alias:'😀'.repeat(33)},{...base,alias:'\ufeff\u2003 alias\u2003'},
 ...[null,'',' '.repeat(8),'x'.repeat(65)].map(alias=>({...base,alias})),
 ...[null,{}, {nonce:'x'.repeat(129),issuedAt:'today',signature:auth.signature},
 {...auth,signature:'0x'+'1'.repeat(128)},{...auth,extra:true}, {...auth,signature:'bad'}].map(auth=>({...base,auth})),
 {action:'list',editorAddress:address,ownerAddresses:[]},
 {action:'list',editorAddress:address,ownerAddresses:[address,address]},
 {action:'list',editorAddress:address,ownerAddresses:[null]},
 {action:'list',editorAddress:'bad',ownerAddresses:[]},
 {...base,action:'delete'}, {...base,action:'invalid'}])cases.push({body});
cases.push({body:base,mode:'auth-error'}, {body:{action:'list',editorAddress:address,ownerAddresses:[]},mode:'db-error'},
 {raw:'{'},{raw:'\ufeff'+JSON.stringify(base)});
for(const entry of cases){
 mode=entry.mode??'normal';calls=[];const raw=entry.raw??JSON.stringify(entry.body);let response:Response;
 try{response=await POST(new Request('http://fixture',{method:'POST',body:raw}));}
 catch{response=new Response(null,{status:500});}
 const text=await response.text();const result=text?JSON.parse(text):null;
 if(result?.correlationId)result.correlationId='generated';
 Object.assign(entry,{raw,status:response.status,result,cache:response.headers.get('cache-control'),calls});
}
console.log(JSON.stringify(cases));
