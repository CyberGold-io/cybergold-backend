"""Acquisition observations preserve connection ownership and exit contracts."""
from contextlib import asynccontextmanager, contextmanager
from unittest.mock import AsyncMock, patch
import unittest

from cybergold_candidate.database import Database
from cybergold_candidate import database


class ModuleBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def connection_case(self, *, error=None, suppressed=False):
        events = []
        sentinel = object()
        class Pool:
            @asynccontextmanager
            async def connection(self):
                events.append('lease-enter')
                try:
                    yield sentinel
                except BaseException as failure:
                    events.append(('lease-exit-error', failure))
                    if not suppressed:
                        raise
                else:
                    events.append('lease-exit-ok')
        @contextmanager
        def stage(name, *, kind):
            events.append((name, kind, 'enter'))
            try:
                yield
            finally:
                events.append((name, kind, 'exit'))
        subject = Database(None)
        subject.get_pool = AsyncMock(return_value=Pool())
        async def use():
            async with subject.connection() as connection:
                self.assertIs(connection, sentinel)
                self.assertEqual(events[-1], ('database.acquire', 'await', 'exit'),
                    'acquisition measurement must stop before the caller owns the connection')
                events.append('user-body')
                if error is not None:
                    raise error
        with patch.object(database, 'stage', stage):
            if error is not None and not suppressed:
                with self.assertRaises(type(error)) as caught:
                    await use()
                self.assertIs(caught.exception, error)
            else:
                await use()
        subject.get_pool.assert_awaited_once()
        self.assertEqual(events[:3], [('database.acquire', 'await', 'enter'), 'lease-enter',
                                     ('database.acquire', 'await', 'exit')])
        self.assertEqual(events[-1], ('lease-exit-error', error) if error is not None else 'lease-exit-ok')

    async def test_acquisition_span_excludes_successful_user_operation(self):
        await self.connection_case()

    async def test_acquisition_preserves_connection_error_propagation(self):
        await self.connection_case(error=RuntimeError('operation failed'))

    async def test_acquisition_preserves_connection_exception_suppression(self):
        await self.connection_case(error=RuntimeError('suppressed operation'), suppressed=True)

    async def test_acquisition_preserves_cancellation_identity_and_exit(self):
        import asyncio
        await self.connection_case(error=asyncio.CancelledError())


if __name__ == '__main__':
    unittest.main()
