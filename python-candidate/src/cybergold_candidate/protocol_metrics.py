"""Best-effort gauges from completed product reads, never RPC at scrape time."""
import asyncio
from collections import Counter
import math
import time

from prometheus_client import Gauge

DEFINITIONS={
    'snapshot_block':'Block of the completed product dashboard snapshot.',
    'snapshot_timestamp_seconds':'Chain timestamp of the completed product snapshot.',
    'supply_cygld':'CYGLD supply from the completed product snapshot.',
    'net_issuance_24h_cygld':"Net issuance over the product snapshot's trailing 24 hours; not a counter.",
    'holders':'Indexed holder count; absent when unknown.',
    'paused':'Snapshot pause state: 1 paused, 0 unpaused; absent when unknown.',
    'activity_indexed_through_block':'Core raw journal cursor for the recent activity sample.',
    'activity_sample_logs':'Size of the most recent Core journal sample, capped at 100 logs.',
    'activity_has_more':'1 means retained Core logs exist before the displayed sample.',
}


class ProtocolMetrics:
    def __init__(self,registry,read_snapshot,read_activity,now=time.time):
        self.registry,self.read_snapshot,self.read_activity,self.now=registry,read_snapshot,read_activity,now
        self.fields={};self.pending=None
        def gauge(name,help,labels):return Gauge('cybergold_protocol_'+name,help,labels,registry=registry)
        self.ok=gauge('read_success','Whether the most recent committed-product read succeeded.',('source',))
        self.observed=gauge('observed_timestamp_seconds','Time of the last successful product read, not chain freshness.',('source',))
        self.reserves=gauge('reserve_tokens','Protocol reserve in token units, not executable DEX liquidity.',('asset',))
        self.weights=gauge('basket_weight_percent','Product basket actual and target weights in percent.',('asset','kind'))
        self.events=gauge('activity_sample_events','Event counts in the latest up-to-100-log sample; not lifetime counts or rates.',('event',))

    def set(self,name,value):
        if type(value) not in (int,float) or not math.isfinite(value):
            metric=self.fields.pop(name,None)
            if metric is not None:self.registry.unregister(metric)
            return
        if name not in self.fields:self.fields[name]=Gauge('cybergold_protocol_'+name,DEFINITIONS[name],registry=self.registry)
        self.fields[name].set(value)

    async def snapshot(self):
        snapshot=await self.read_snapshot()
        if not snapshot or not snapshot.get('enabled'):
            for name in list(DEFINITIONS)[:6]:self.set(name,None)
            self.reserves.clear();self.weights.clear();return
        metrics=snapshot['metrics']
        self.set('snapshot_block',float(snapshot['snapshotBlock']))
        self.set('snapshot_timestamp_seconds',snapshot['chainHeadTimestampMs']/1000)
        self.set('supply_cygld',metrics.get('currentTotalSupplyCygld'))
        self.set('net_issuance_24h_cygld',metrics.get('netIssuance24hCygld'))
        self.set('holders',metrics.get('holderCount'))
        self.set('paused',int(metrics['paused']) if type(metrics.get('paused')) is bool else None)
        self.reserves.clear();self.weights.clear()
        for asset in (snapshot.get('basket') or {}).get('assets',[]):
            address=asset['address'].lower()
            reserve=asset.get('reserveBalance')
            if type(reserve) in (int,float) and math.isfinite(reserve):self.reserves.labels(address).set(reserve)
            for kind,key in [('actual','actualPercent'),('target','targetPercent')]:
                value=asset.get(key)
                if type(value) in (int,float) and math.isfinite(value):self.weights.labels(address,kind).set(value)

    async def activity(self):
        activity=await self.read_activity();self.events.clear()
        if not activity['enabled']:
            for name in list(DEFINITIONS)[6:]:self.set(name,None)
            return
        block=activity['indexedThroughBlock']
        self.set('activity_indexed_through_block',float(block) if block is not None else None)
        self.set('activity_sample_logs',len(activity['events']));self.set('activity_has_more',int(activity['hasMore']))
        counts=Counter(event['eventName'] if event.get('eventName') is not None else 'unknown' for event in activity['events'])
        for name,count in counts.items():self.events.labels(name).set(count)

    async def collect(self,source,work):
        try:
            await work();self.ok.labels(source).set(1);self.observed.labels(source).set(self.now())
        except Exception:
            try:self.ok.labels(source).set(0)
            except Exception:pass

    async def _refresh(self):
        try:await asyncio.gather(self.collect('snapshot',self.snapshot),self.collect('activity',self.activity))
        finally:self.pending=None

    def refresh(self):
        if self.pending is None:self.pending=asyncio.create_task(self._refresh())
        return self.pending

    async def close(self):
        if self.pending is not None:
            self.pending.cancel();await asyncio.gather(self.pending,return_exceptions=True)
