import {Registry} from '@prometheus-io/client';
import {createProtocolMetrics} from '../../src/server/protocolMetrics';
const registry=new Registry();let mode='normal';let now=10;
const snapshot={enabled:true,snapshotBlock:'26075596',chainHeadTimestampMs:1790000000000,
 metrics:{currentTotalSupplyCygld:124.5,netIssuance24hCygld:-2.5,holderCount:null,paused:false},
 basket:{assets:[{address:'0xABC',reserveBalance:25.5,actualPercent:45,targetPercent:50}]}};
const activity={enabled:true,indexedThroughBlock:'26075596',hasMore:true,
 events:[{eventName:'DiamondCut'},{eventName:'DiamondCut'},{eventName:null}]};
const metrics=createProtocolMetrics(registry,async()=>{
 if(mode==='error')throw new Error('private fixture');
 return mode==='disabled'?{enabled:false}:snapshot as any;},async()=>mode==='disabled'?{enabled:false,events:[]}:activity as any,()=>now);
const read=async()=>{
 const values:any[]=[];
 for(const metric of registry.getMetricsAsArray())for(const value of (await metric.get()).values)
  values.push({name:metric.name,value:value.value,labels:value.labels});
 return values.sort((a,b)=>JSON.stringify(a).localeCompare(JSON.stringify(b)));
};
const cases:any[]=[];
for(const value of ['normal','error','empty-assets','disabled']){
 mode=value;now+=10;if(mode==='empty-assets')snapshot.basket.assets=[];
 await metrics.refresh();cases.push({mode,now,values:await read()});
}
console.log(JSON.stringify({snapshot:{...snapshot,basket:{assets:[{address:'0xABC',reserveBalance:25.5,actualPercent:45,targetPercent:50}]}},activity,cases}));
