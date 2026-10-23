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
cases.push({body:{...base,requestId:base.attemptId,correlationId:base.quoteId,workId:base.attemptId,
  side:'buy',strategy:'core',stage:'simulation',errorClassification:'quote-contract-reverted',
  tokenIn:'0x'+'1'.repeat(40),tokenOut:'0x'+'0'.repeat(40),amount:(2n**256n-1n).toString(),
  inputMaximum:'100',outputMinimum:'99',blockNumber:'123',blockHash:'0x'+'a'.repeat(64)}});
cases.push({body:{...base,requestId:'secret',correlationId:'secret',workId:'secret',strategy:'unknown',stage:'unknown',
  tokenIn:'secret',tokenOut:'secret',amount:(2n**256n).toString(),inputMaximum:'-1',outputMinimum:'1.1',
  blockNumber:'1\n',blockHash:'secret',errorClassification:'secret'}});
for(const errorClassification of ['quote-service-unavailable','quote-stream-interrupted','quote-invalid-input','quote-request-limit'])
  cases.push({body:{...base,errorClassification}});
for(const errorClassification of ['redemption-supply-exceeded','redemption-capacity-exceeded',
  'insufficient-reserve-balance','insufficient-recovery-shares','insufficient-protocol-supply'])
  cases.push({body:{...base,errorClassification,quoteDiagnostics:{
    routeWave:{legs:{count:1,rows:[{index:0,failureCounts:[{code:errorClassification,count:1}]}]}},
    providerQualifications:{provider:'core',attempts:1,rejected:1,
      rows:[{attempt:1,stage:'basket-preview',outcome:'rejected',code:errorClassification}]}}}});
for(const constraint of [null, true, {}, {kind:'issuance-cap',quantity:'gross-cygld-mint',limitKind:'effective-supply-cap',
  requestedRaw:'20',availableRaw:'10',currentSupplyRaw:'90',limitRaw:'100',private:'fixture-private-constraint'},
  {kind:'redemption-supply',quantity:'gross-cygld-input',requestedRaw:'100'},
  {kind:'secret',quantity:'secret',limitKind:'secret',requestedRaw:(2n**256n).toString(),availableRaw:'-1',currentSupplyRaw:'1\n',limitRaw:100}])
  cases.push({body:{...base,constraint}});
const providerStages=['composition','basket-preview','initial-preview','execution-search','expected-input-search',
  'final-preview','tolerance','canonicality','selection','route-pricing','fee-bounds','qualification','retained-validation'];
const providerOutcomes=['running','qualified','rejected','not-improved','cancelled','superseded'];
for(const provider of ['core','market'])for(const stage of providerStages)for(const outcome of providerOutcomes)
  cases.push({body:{...base,quoteDiagnostics:{phase:'initial-search',providerQualifications:{provider,attempts:1,pending:0,
    selectedAttempt:1,selectionReason:'best-initial',firstQualifiedMs:40.25,selectionMs:5000,
    canonicalCompletedMs:5001.25,cleanupCompletedMs:5000.5,
    rows:[{attempt:1,stage,outcome,code:'quote-no-route',targetAmount:'0',maximumAmountIn:(2n**256n-1n).toString(),
      startedMs:10.5,completedMs:40.25,elapsedMs:29.75,executionAmount:'400',quotedInput:'100',quotedOutput:'400',
      inputMaximum:'100',outputMinimum:'396',pools:[{protocol:'v4',poolId:'0x'+'A'.repeat(64),raw:'fixture-private-pool'}],omittedPools:0,
      observedAmountIn:'1',signature:'fixture-private-signature'}]},routeWave:{subphase:'structured-search',legs:{count:1,rows:[{
      index:0,inputAsset:'0x'+'A'.repeat(40),amount:'0',bestAvailable:false,failureCounts:[{code:'quote-timeout',count:1}],
      bestPools:[{protocol:'v3',poolId:'v3:0x'+'A'.repeat(40)+':0x'+'B'.repeat(40)+':0000500'}],
      request:'fixture-private-request'}]}},private:'fixture-private-provider'}}});
for(const quoteDiagnostics of [null,[],{phase:'context',providerQualifications:{provider:[],attempts:1}},
  {phase:'context',providerQualifications:{provider:'core',attempts:1,rows:[{attempt:1,stage:[],outcome:'rejected',code:{}}]}},
  {routeWave:{legs:{count:1,rows:[{index:0,amount:'1\n',inputAsset:'0x'+'A'.repeat(40)+'\n',
    failureCounts:[{code:[],count:1}],bestPools:[{protocol:[],poolId:'0x'+'A'.repeat(40)},
      {protocol:'v3',poolId:'v3:0x'+'A'.repeat(40)+':0x'+'B'.repeat(40)+':3000\n'}]}]}}},
  {providerQualifications:{provider:'market',attempts:1,rows:[{attempt:1,stage:'qualification',outcome:'rejected',
    code:'quote-contract-reverted',targetAmount:'00',maximumAmountIn:(2n**256n).toString(),observedAmountIn:'-1'}]}}])
  cases.push({body:{...base,quoteDiagnostics}});
for(const provider of ['core','market'])for(const selectionReason of ['complete','best-initial','first-extension','timeout',[],{},'private-reason'])
  cases.push({body:{...base,quoteDiagnostics:{providerQualifications:{provider,attempts:1,selectionReason,
    selectedAttempt:true,selectionMs:-1,firstQualifiedMs:1e12+1,cleanupCompletedMs:'private-ms',
    rows:[{attempt:1,stage:'selection',outcome:'qualified',executionAmount:'00',quotedInput:(2n**256n).toString(),
      quotedOutput:'1\n',inputMaximum:'-1',outputMinimum:1,startedMs:true,completedMs:-1,elapsedMs:'private-ms',
      pools:[{protocol:'v4',poolId:'0x'+'A'.repeat(64)+'\n'}]}]}}}});
cases.push({body:base,type:'text/plain'},{body:base,type:'application/json; charset=utf-8'});
for(const entry of cases){
  const logs:any[]=[];
  const app=Fastify({logger:{stream:{write(value:string){logs.push(JSON.parse(value));}}} as any});
  await registerClientDiagnostics(app);
  const raw=entry.raw??JSON.stringify(entry.body);
  const response=await app.inject({method:'POST',url:'/api/diagnostics',payload:raw,
    headers:{'content-type':entry.type??'application/json'}});
  const records=logs.filter(value=>value.event==='client_diagnostic').map(({level,time,pid,hostname,msg,reqId,requestId,diagnosticRequestId,release,...value})=>value);
  Object.assign(entry,{raw,status:response.statusCode,result:response.json(),cache:response.headers['cache-control'],records,
    projection:projectClientDiagnostic(entry.body)});
  await app.close();
}
console.log(JSON.stringify(cases));
