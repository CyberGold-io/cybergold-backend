import asyncio
import json
from pathlib import Path
import sys

from cybergold_candidate.rpc_http import RpcReadPacer, retry_delay


async def main(path):
    expected = json.loads(Path(path).read_text())
    clock = [1.0]
    pacer = RpcReadPacer(now=lambda: clock[0])
    starts = []
    async def record(count):
        await pacer.wait(count)
        starts.append(round(clock[0] * 1000))
    tasks = [asyncio.create_task(record(count)) for count in (5, 2, 5)]
    await asyncio.sleep(0)
    clock[0] = 1.625; pacer.drain(); await asyncio.sleep(0)
    clock[0] = 1.875; pacer.drain(); await asyncio.gather(*tasks)
    assert starts == expected['budgetStarts']
    pacer.close()

    clock[0] = 1
    pacer = RpcReadPacer(now=lambda: clock[0])
    await pacer.wait(5)
    starts.clear()
    queued = asyncio.create_task(record(5)); await asyncio.sleep(0)
    pacer.pause(2)
    clock[0] = 2.999; pacer.drain(); await asyncio.sleep(0)
    assert not starts and expected['queuedDuringCooldown'] is None
    clock[0] = 3; pacer.drain(); await queued
    assert starts == [expected['cooldownStart']]
    pacer.close()

    clock[0] = 1
    pacer = RpcReadPacer(now=lambda: clock[0])
    await pacer.wait(5)
    starts.clear()
    cancelled = asyncio.create_task(pacer.wait(5))
    following = asyncio.create_task(record(1)); await asyncio.sleep(0)
    cancelled.cancel()
    await asyncio.gather(cancelled, return_exceptions=True)
    clock[0] = 1.625; pacer.drain(); await following
    assert cancelled.cancelled() == expected['cancelled']
    assert starts == [expected['afterCancelStart']]
    pacer.close()
    for case in expected['retryDelays']:
        assert retry_delay(case['value'], now=lambda: 1790762400) * 1000 == case['delay'], case
    print('PASS: actual Node/Python pacer budget, queued cooldown, cancellation and ten Retry-After comparisons')


if __name__ == '__main__':
    asyncio.run(main(sys.argv[1]))
