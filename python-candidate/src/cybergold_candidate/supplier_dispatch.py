"""Bound in-flight product work without rejecting or truncating caller inputs."""
import asyncio


SUPPLIER_CONCURRENCY = 8


async def dispatch(items, supplier):
    items = list(items)
    results = [None] * len(items)
    pending = iter(enumerate(items))

    async def worker():
        for index, item in pending:
            results[index] = await supplier(item)

    workers = [asyncio.create_task(worker()) for _ in range(min(SUPPLIER_CONCURRENCY, len(items)))]
    try:
        await asyncio.gather(*workers)
        return results
    finally:
        # Supplier failure or the existing operation deadline must not leave
        # sibling reads running after the operation has already returned.
        for task in workers:
            task.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
