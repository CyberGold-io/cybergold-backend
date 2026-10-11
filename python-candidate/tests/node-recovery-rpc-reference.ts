import {createRecoveryRpcReader} from '../../src/server/recovery/rpcPortfolio';
import {createRecoveryPortfolioReader} from '../../src/server/recovery/portfolioReader';
import {CORE_DIAMOND_ABI} from '../../src/contracts/generated/coreDiamond';
import {GOVERNANCE_DIAMOND_ABI} from '../../src/contracts/generated/governanceDiamond';
import {encodeFunctionData,encodeFunctionResult,decodeFunctionData} from 'viem';
import {writeFileSync} from 'node:fs';
const address=(i:number)=>'0x'+i.toString(16).padStart(40,'0');
const core=address(1000),governance=address(1001),holder=address(1002),assets=[address(1),address(2)];
const hash='0x'+'a'.repeat(64);
const coreNames=['outstandingRecoveryAssetCount','outstandingRecoveryAssets','paused','recoveryPool',
  'reserveLifecycle','reserveCustodyStatus','balanceOfBatch','previewRedeemRecoveryShares'];
const govNames=['trustedRecoveryFundCore','paused','recoveryFundTreasuryStatus','assetRecoveryFund','previewAssetRecoveryFundPurchase'];
const abi:any={core:CORE_DIAMOND_ABI.filter(x=>x.type==='function'&&coreNames.includes(x.name)),
  governance:GOVERNANCE_DIAMOND_ABI.filter(x=>x.type==='function'&&govNames.includes(x.name))};
writeFileSync('python-candidate/src/cybergold_candidate/recovery-rpc-abi.json',JSON.stringify(abi,null,2)+'\n');
const cases=[];
for(const fault of ['healthy','not-configured','empty','chain','canonical','custody','lifecycle','supply',
  'preview','fund-core','fund-transport','fund-deficit','fund-inactive','fund-terms','fund-preview-generation','fund-offer-transport']){
  const routes:any[]=[];
  const add=(contract:string,name:string,value:any,failure=false)=>routes.push({contract,name,
    selector:encodeFunctionData({abi:abi[contract],functionName:name,args:abi[contract].find((x:any)=>x.name===name).inputs.map((x:any)=>
      x.type==='address'?assets[0]:x.type==='address[]'?[holder]:x.type==='uint256[]'?[1n]:0n)} as any).slice(0,10),
    response:failure?null:encodeFunctionResult({abi:abi[contract],functionName:name,result:value} as any)});
  const external=9007199254740993n;
  add('core','outstandingRecoveryAssetCount',fault==='empty'?0n:2n);
  add('core','outstandingRecoveryAssets',[fault==='empty'?[]:assets,fault==='empty'?0n:2n]);
  add('core','paused',false);
  add('core','recoveryPool',{impaired:false,coreAttachedShares:0n,externalShares:external,redeemableRaw:2n,
    cygldPerAssetRawFp18:10n**18n,cygldSupplyCap:external,referenceShares:external,referenceValueCygld:100n,shareDecimals:18});
  add('core','reserveLifecycle',{lifecycle:fault==='lifecycle'?4:1,exitEntitlementRaw:0n});
  add('core','reserveCustodyStatus',{lifecycle:1,poolImpaired:false,redeemablePoolRaw:2n,
    coreAttachedShares:0n,externalShares:fault==='supply'?1n:external,exitEntitlementRaw:0n,
    liveBalanceAvailable:fault!=='custody',liveRawCustody:fault==='custody'?0n:2n,activeAvailableRaw:0n,
    poolRawDeficit:0n,exitEntitlementDeficitRaw:0n});
  add('core','balanceOfBatch',fault==='empty'?[]:[external,0n]);
  add('core','previewRedeemRecoveryShares',2n**256n-1n,fault==='preview');
  add('governance','trustedRecoveryFundCore',fault==='fund-core'?holder:core,fault==='fund-transport');
  add('governance','paused',false);
  add('governance','recoveryFundTreasuryStatus',[fault==='fund-deficit'?0n:100n,0n,1n]);
  add('governance','assetRecoveryFund',{generation:fault==='fund-terms'?0n:2n,coverageShares:fault==='fund-inactive'?0n:external,
    purchasedShares:0n,initialCygldCommitment:fault==='fund-inactive'?0n:100n},fault==='fund-offer-transport');
  add('governance','previewAssetRecoveryFundPurchase',[fault==='fund-preview-generation'?3n:2n,100n]);
  const calls:any[]=[];
  const fakeFetch=(async(_url:any,init:any)=>{
    const input=JSON.parse(init.body);
    const reply=(request:any)=>{
      let result:any;
      if(request.method==='eth_chainId')result=fault==='chain'?'0x1':'0x7a6a';
      else if(request.method.startsWith('eth_getBlock'))result={hash:fault==='canonical'&&request.params[0]!=='latest'?('0x'+'b'.repeat(64)):hash,
        number:'0x20000000000001',timestamp:'0x1'};
      else if(request.method==='eth_call'){
        const contract=request.params[0].to.toLowerCase()===core?'core':'governance';
        const route=routes.find(x=>x.contract===contract&&x.selector===request.params[0].data.slice(0,10));
        const decoded=decodeFunctionData({abi:abi[contract],data:request.params[0].data});
        calls.push({contract,name:decoded.functionName,args:decoded.args??[],target:request.params[1]});
        if(route.response===null)return {jsonrpc:'2.0',id:request.id,error:{code:-32000,message:'fixture-private-rpc'}};
        result=route.response;
      }else throw new Error('Unexpected fixture method '+request.method);
      return {jsonrpc:'2.0',id:request.id,result};
    };
    return new Response(JSON.stringify(Array.isArray(input)?input.map(reply):reply(input)),{headers:{'content-type':'application/json'}});
  }) as typeof fetch;
  const environment={RPC_URL:'http://fixture-rpc',RPC_AUTHORIZATION:'Bearer fixture-private',NEXT_PUBLIC_CHAIN_ID:'31338',
    NEXT_PUBLIC_CORE_DIAMOND_ADDRESS:core,NEXT_PUBLIC_GOVERNANCE_DIAMOND_ADDRESS:fault==='not-configured'?undefined:governance};
  let outcome:any;
  try{outcome={result:await createRecoveryPortfolioReader(createRecoveryRpcReader(environment,fakeFetch))(holder as any)};}
  catch(error){outcome={error:(error as Error).message};}
  cases.push({fault,core,governance,holder,hash,routes,outcome,calls});
}
console.log(JSON.stringify(cases,(_key,value)=>typeof value==='bigint'?value.toString():value));
