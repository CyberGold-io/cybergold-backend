import asyncio
import json
from pathlib import Path
import sys

from prometheus_client import CollectorRegistry,generate_latest
from cybergold_candidate.protocol_metrics import ProtocolMetrics


async def run(path):
    reference=json.loads(Path(path).read_text());registry=CollectorRegistry();mode='normal';now=10;calls=0
    async def snapshot():
        nonlocal calls
        calls+=1
        if mode=='error':raise ValueError('private fixture')
        if mode=='disabled':return {'enabled':False}
        return {**reference['snapshot'],'basket':{'assets':[]} if mode=='empty-assets' else reference['snapshot']['basket']}
    async def activity():return {'enabled':False,'events':[]} if mode=='disabled' else reference['activity']
    metrics=ProtocolMetrics(registry,snapshot,activity,lambda:now)
    for case in reference['cases']:
        mode=case['mode'];now=case['now']
        first=metrics.refresh();assert metrics.refresh() is first
        await first
        actual=[{'name':sample.name,'value':sample.value,'labels':sample.labels}
            for family in registry.collect() for sample in family.samples]
        assert sorted(actual,key=lambda row:json.dumps(row,sort_keys=True))==sorted(case['values'],key=lambda row:json.dumps(row,sort_keys=True)),(mode,actual,case['values'])
        count=calls
        for _ in range(10):assert 'private fixture' not in generate_latest(registry).decode()
        assert calls==count
    await metrics.close()
    print('PASS: actual Node/Python protocol gauges across committed data, DB failure, changed reserves and disabled sources; coalesced reads and memory-only scrapes')


asyncio.run(run(sys.argv[1]))
