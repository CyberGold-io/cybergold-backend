import {setTimeout} from 'node:timers/promises';
import {createBackendServer} from '../../src/http-server';
import {marketFeed} from '../../src/server/market-cache';
import {httpRequests,cacheRequests,marketRefreshes,marketLastFresh,indexerLag,indexerObserved,indexerReconciled,observeIndexer}
  from '../../src/server/metrics';
Date.now=()=>1790762400000;
const values=async(metric:any)=>(await metric.get()).values.map(({value,labels}:any)=>({value,labels}));
const api=await createBackendServer('api',{logger:false});
try{
  await api.inject({method:'POST',url:'/api/rpc?private=fixture-secret',payload:'{'});
  await api.inject('/private-wallet-0xabc?bearer=fixture-secret');
  await api.inject('/metrics');await api.inject('/metrics');
}finally{await api.close();}
let count=0;
const feed=marketFeed(async(previous:any)=>{count++;await setTimeout(2);return {
  payload:{fetchedAt:previous?.fetchedAt??'2026-09-28T00:00:00.000Z',stale:count>1},isFresh:count===1};},20,'gold');
await Promise.all(Array.from({length:20},()=>feed()));await feed();
await setTimeout(25);await feed();await feed();
const unknown=await values(indexerLag);
observeIndexer({status:'busy',dashboardHistoryProgress:null});
observeIndexer({status:'incomplete',dashboardHistoryProgress:{formatVersion:1,startBlock:'1',indexedThroughBlock:'100',
  networkFinalizedBlock:'150',indexedThroughDate:'2026-09-29T00:00:00Z',networkFinalizedDate:'2026-09-29T00:10:00Z',percent:66}});
observeIndexer({status:'deferred-cadence',dashboardHistoryProgress:null});
observeIndexer({status:'reconciled',dashboardHistoryProgress:null});
console.log(JSON.stringify({http:await values(httpRequests),cache:await values(cacheRequests),
  refresh:await values(marketRefreshes),fresh:await values(marketLastFresh),unknown,
  lag:await values(indexerLag),observed:await values(indexerObserved),reconciled:await values(indexerReconciled)}));
