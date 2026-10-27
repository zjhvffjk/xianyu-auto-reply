"""后台账号启动不会阻塞HTTP就绪，退出时必须回收调度任务。"""
import asyncio
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

from app.services.account_startup import AccountStartup


class AccountStartupTests(unittest.IsolatedAsyncioTestCase):
    def manager(self):
        return NS(startup_total=3, startup_processed=1, _loading_account_changes=None,
                  start=AsyncMock(), stop=AsyncMock())

    async def test_yields_before_slow_start_finishes_and_cancels_on_exit(self):
        manager = self.manager()
        waiting = asyncio.Event()
        manager.start.side_effect = waiting.wait
        startup = AccountStartup(manager, True)
        async with startup.run():
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            self.assertFalse(startup.task.done())
            self.assertEqual(startup.get_status()['status'], 'starting')
            self.assertEqual(startup.get_status()['processed'], 1)
        self.assertTrue(startup.task.cancelled())
        manager.stop.assert_awaited_once()
        self.assertIsNone(manager._loading_account_changes)

    async def test_failed_background_start_is_visible_and_cleanup_still_runs(self):
        manager = self.manager()
        manager.start.side_effect = RuntimeError('test account load failed')
        startup = AccountStartup(manager, True)
        async with startup.run():
            await startup.task
            self.assertEqual(startup.get_status()['status'], 'failed')
            self.assertIn('test account load failed', startup.get_status()['message'])
        manager.stop.assert_awaited_once()

    async def test_disabled_start_does_not_connect_accounts(self):
        manager = self.manager()
        startup = AccountStartup(manager, False)
        async with startup.run():
            self.assertIsNone(startup.task)
            self.assertEqual(startup.get_status()['status'], 'disabled')
        manager.start.assert_not_awaited()
        manager.stop.assert_awaited_once()

    async def test_completion_is_reported_as_scheduled_not_connected(self):
        manager = self.manager()
        startup = AccountStartup(manager, True)
        async with startup.run():
            await startup.task
            self.assertEqual(startup.get_status()['status'], 'completed')
            self.assertIn('连接状态请查看账号管理', startup.get_status()['message'])


if __name__ == '__main__':
    unittest.main()
