import Fastify from 'fastify';
import {registerClientDiagnostics,projectClientDiagnostic} from '../../src/server/clientDiagnostics';
const base={operation:'quote',outcome:'succeeded',reason:'unknown',direction:'issue',route:'basket',inputMode:'exact-in',
  walletStep:'signature',attemptId:'11111111-1111-4111-8111-111111111111',quoteId:'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
  transactionHash:'0x'+'A'.repeat(64),durationMs:10,chainId:31338,assetCount:2,
  errorCode:-32603,errorSelector:'0xAbCd0123',raw:'fixture-private-raw',errorArgs:['fixture-private-argument'],
  privateBearer:'fixture-private-bearer',address:'0x'+'b'.repeat(40),error:'fixture-private-error',parameters:{secret:'private'}};
const cases:any[]=[];
for(const body of [null,[],{},true,'text',base,{...base,operation:'invalid'},
  {...base,durationMs:-1,chainId:1.5,assetCount:true},{...base,quoteId:'bad',transactionHash:'bad'},
  {...base,durationMs:9007199254740992},{...base,durationMs:9007199254740991},
  {...base,attemptId:base.attemptId.toUpperCase()}])cases.push({body});
for(const errorCode of [-32603,4001,0,-Number.MAX_SAFE_INTEGER,Number.MAX_SAFE_INTEGER,true,false,'-32603',null,{},1.5,
  Number.MAX_SAFE_INTEGER+1,-Number.MAX_SAFE_INTEGER-1])cases.push({body:{...base,errorCode}});
for(const errorSelector of ['0x12345678',true,null,{},'12345678','0X12345678','0x','0x1234567','0x123456789',
  '0x1234567z','0x12345678\n','0x12345678'+'ab'.repeat(32)])cases.push({body:{...base,errorSelector}});
for(const raw of ['{','', '\ufeff'+JSON.stringify(base), '{"__proto__":{}}','{"constructor":{"prototype":{}}}',
  '{"parameters":{"constructor":{}}}',' '.repeat(1048577)])cases.push({raw});
cases.push({body:base,type:'text/plain'},{body:base,type:'application/json; charset=utf-8'});
for(const entry of cases){
  const logs:any[]=[];
  const app=Fastify({logger:{stream:{write(value:string){logs.push(JSON.parse(value));}}} as any});
  await registerClientDiagnostics(app);
  const raw=entry.raw??JSON.stringify(entry.body);
  const response=await app.inject({method:'POST',url:'/api/diagnostics',payload:raw,
    headers:{'content-type':entry.type??'application/json'}});
  const records=logs.filter(value=>value.event==='client_diagnostic').map(({level,time,pid,hostname,msg,reqId,requestId,release,...value})=>value);
  Object.assign(entry,{raw,status:response.statusCode,result:response.json(),cache:response.headers['cache-control'],records,
    projection:projectClientDiagnostic(entry.body)});
  await app.close();
}
console.log(JSON.stringify(cases));
