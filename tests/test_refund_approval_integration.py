"""隔离MySQL + 模拟平台和短期缓存；绝不调用真实退款。"""
import asyncio
import json
import sys
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
from uuid import uuid4
sys.path.insert(0, '/app/backend-web')
from sqlalchemy import delete
from common.db.session import async_engine, async_session_maker
from common.models.refund_approval import RefundApproval
from common.models.xy_account import XYAccount
from common.services.refund_client import valid_verification_url, RefundPlatformError
from app.services.refund_approval_service import RefundApprovalService


class Cache:
    def __init__(self): self.values = {}
    async def set(self, key, value, ex): self.values[key] = value
    async def get(self, key): return self.values.get(key)
    async def delete(self, key): self.values.pop(key, None)


class RefundApprovalTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.account = NS(account_id='test-ra-'+uuid4().hex[:20], owner_id=-2026102601)
        self.actor = -2026102601
        self.entry = dict(order_no='test-order', refund_id='test-refund', refund_amount='0.10')
        self.row = dict(**self.entry, eligible=True)
        self.cache = Cache()
        self.platform = NS(applications=AsyncMock(side_effect=lambda: [self.row]),
            verification=AsyncMock(return_value=dict(verify_url='https://pcauth-site.alipay.com/home?test', token='test-not-real')),
            agree=AsyncMock(return_value='success'))

    async def asyncTearDown(self):
        async with async_session_maker() as s:
            await s.execute(delete(RefundApproval).where(RefundApproval.account_id == self.account.account_id))
            await s.commit()
        await async_engine.dispose()

    def service(self, session, actor=None):
        return RefundApprovalService(session, self.account, actor or self.actor, self.platform, self.cache)

    async def prepare(self):
        async with async_session_maker() as s:
            op = (await self.service(s).prepare([self.entry]))[0]
            if op['id']:
                return await self.service(s).verification(op['id'])
            return op

    async def refresh_verification(self, operation_id):
        import httpx
        from fastapi import FastAPI
        from app.api.routes import refund_tools
        app = FastAPI()
        app.include_router(refund_tools.router)
        app.dependency_overrides[refund_tools.get_current_active_user] = lambda: NS(id=self.actor)
        async with async_session_maker() as session:
            async def database():
                yield session
            app.dependency_overrides[refund_tools.get_db_session] = database
            with patch.object(refund_tools, 'approval_service', return_value=self.service(session)):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
                    response = await client.post(
                        f'/refund-tools/{self.account.account_id}/approvals/{operation_id}/verification',
                        json={'refresh': True})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['data']

    async def test_manual_refresh_replaces_unusable_context_without_refunding(self):
        op = await self.prepare()
        self.platform.verification.return_value = dict(
            verify_url='https://pcauth-site.alipay.com/home?fresh-test', token='fresh-test-not-real')
        renewed = await self.refresh_verification(op['id'])
        self.assertEqual(renewed['id'], op['id'])
        self.assertEqual(renewed['status'], 'awaiting_verification')
        self.assertNotEqual(renewed['verification_url'], op['verification_url'])
        context = json.loads(await self.cache.get('refund-approval-context:'+op['id']))
        self.assertEqual(context['token'], 'fresh-test-not-real')
        self.platform.agree.assert_not_awaited()

    async def test_manual_refresh_cannot_restart_financial_outcomes(self):
        op = await self.prepare()
        original = await self.cache.get('refund-approval-context:'+op['id'])
        for status in ('submitting', 'submitted', 'unknown', 'success', 'failed', 'conflict'):
            with self.subTest(status=status):
                async with async_session_maker() as session:
                    record = await session.get(RefundApproval, op['id'])
                    record.status = status
                    await session.commit()
                result = await self.refresh_verification(op['id'])
                self.assertEqual(result['status'], status)
                self.assertIsNone(result['verification_url'])
                self.assertEqual(await self.cache.get('refund-approval-context:'+op['id']), original)
        self.platform.verification.assert_awaited_once()
        self.platform.agree.assert_not_awaited()

    async def test_refresh_failure_discards_stale_context_without_refunding(self):
        op = await self.prepare()
        self.platform.verification.side_effect = RefundPlatformError('view unavailable')
        result = await self.refresh_verification(op['id'])
        self.assertEqual(result['status'], 'verification_failed')
        self.assertIsNone(result['verification_url'])
        self.assertIsNone(await self.cache.get('refund-approval-context:'+op['id']))
        self.platform.agree.assert_not_awaited()

    async def test_preparation_never_refunds_and_duplicate_reuses_operation(self):
        first, second = await self.prepare(), await self.prepare()
        self.assertEqual(first['id'], second['id'])
        self.assertEqual(first['status'], 'awaiting_verification')
        self.platform.verification.assert_awaited_once()
        self.platform.agree.assert_not_awaited()
        self.assertNotIn('token', json.dumps(first))

    async def test_duplicate_with_mapped_account_keeps_queue_and_manual_verification_usable(self):
        other_entry = dict(order_no='test-order-2', refund_id='test-refund-2', refund_amount='0.10')
        self.platform.applications.side_effect = lambda: [self.row, dict(**other_entry, eligible=True)]
        async with async_session_maker() as session:
            account = XYAccount(account_id=self.account.account_id, owner_id=self.account.owner_id,
                                cookie='test-cookie-not-real', login_method='cookie')
            session.add(account)
            await session.commit()
            try:
                service = RefundApprovalService(session, account, self.actor, self.platform, self.cache)
                first = (await service.prepare([self.entry]))[0]
                repeated = await service.prepare([self.entry, other_entry])
                self.assertEqual(repeated[0]['id'], first['id'])
                self.assertEqual([op['status'] for op in repeated], ['queued', 'queued'])
                verified = await service.verification(first['id'])
                self.assertEqual(verified['status'], 'awaiting_verification')
                self.assertEqual((await service.confirm(first['id']))['status'], 'success')
                self.platform.agree.assert_awaited_once_with('test-refund', 'test-not-real')
            finally:
                await session.rollback()
                await session.execute(delete(XYAccount).where(XYAccount.account_id == self.account.account_id))
                await session.commit()

    async def test_verified_submit_once_and_no_token_in_result(self):
        op = await self.prepare()
        async with async_session_maker() as s:
            result = await self.service(s).confirm(op['id'])
        self.assertEqual(result['status'], 'success')
        self.platform.agree.assert_awaited_once_with('test-refund', 'test-not-real')
        self.assertIsNone(await self.cache.get('refund-approval-context:'+op['id']))
        async with async_session_maker() as s:
            self.assertEqual((await self.service(s).confirm(op['id']))['status'], 'success')
        self.platform.agree.assert_awaited_once()

    async def test_stale_orm_snapshot_cannot_resubmit_while_another_window_is_submitting(self):
        op=await self.prepare()
        entered,release=asyncio.Event(),asyncio.Event()
        calls=0
        async def agree(*args):
            nonlocal calls
            calls+=1
            if calls==1:
                entered.set()
                await release.wait()
            return 'success'
        self.platform.agree.side_effect=agree
        async with async_session_maker() as auto_db, async_session_maker() as manual_db:
            stale=await auto_db.get(RefundApproval,op['id'])
            self.assertEqual(stale.status,'awaiting_verification')
            task=asyncio.create_task(self.service(manual_db).confirm(op['id']))
            try:
                await asyncio.wait_for(entered.wait(),5)
                await asyncio.wait_for(self.service(auto_db).confirm(op['id']),5)
                self.assertEqual(calls,1)
            finally:
                await auto_db.rollback()  # 与请求/执行器退出时一致：释放本次只读锁。
                release.set()
                await asyncio.wait_for(task,5)

    async def test_amount_changed_after_preview_is_blocked(self):
        op = await self.prepare()
        self.row['refund_amount'] = '1.01'
        async with async_session_maker() as s:
            self.assertEqual((await self.service(s).confirm(op['id']))['status'], 'conflict')
        self.platform.agree.assert_not_awaited()

    async def test_closed_or_ineligible_application_is_blocked(self):
        self.row['eligible'] = False
        result = await self.prepare()
        self.assertEqual(result['status'], 'conflict')
        self.platform.verification.assert_not_awaited()
        self.platform.agree.assert_not_awaited()

    async def test_timeout_is_unknown_and_never_retried(self):
        op = await self.prepare(); self.platform.agree.side_effect = TimeoutError()
        async with async_session_maker() as s:
            self.assertEqual((await self.service(s).confirm(op['id']))['status'], 'unknown')
        async with async_session_maker() as s:
            self.assertEqual((await self.service(s).confirm(op['id']))['status'], 'unknown')
        self.platform.agree.assert_awaited_once()

    async def test_accepted_is_not_claimed_as_refund_complete(self):
        op = await self.prepare(); self.platform.agree.return_value = 'submitted'
        async with async_session_maker() as s:
            self.assertEqual((await self.service(s).confirm(op['id']))['status'], 'submitted')
        async with async_session_maker() as s:
            self.assertEqual((await self.service(s).confirm(op['id']))['status'], 'submitted')
        self.platform.agree.assert_awaited_once()

    async def test_expired_verification_is_not_submitted(self):
        op = await self.prepare(); self.cache.values.clear()
        async with async_session_maker() as s:
            self.assertEqual((await self.service(s).confirm(op['id']))['status'], 'expired')
        self.platform.agree.assert_not_awaited()
        async with async_session_maker() as s:
            renewed = await self.service(s).verification(op['id'])
        self.assertEqual(renewed['status'], 'awaiting_verification')
        self.assertEqual(self.platform.verification.await_count, 2)
        self.platform.agree.assert_not_awaited()

    async def test_other_actor_cannot_confirm_or_get_verification_context(self):
        op = await self.prepare()
        async with async_session_maker() as s:
            result = (await self.service(s, self.actor-1).prepare([self.entry]))[0]
            self.assertIsNone(result['verification_url'])
            with self.assertRaises(LookupError):
                await self.service(s, self.actor-1).confirm(op['id'])
        self.platform.agree.assert_not_awaited()

    async def test_double_confirm_does_not_send_two_refunds(self):
        op = await self.prepare()
        async def do_confirm():
            async with async_session_maker() as s: return await self.service(s).confirm(op['id'])
        results = await asyncio.gather(do_confirm(), do_confirm())
        self.platform.agree.assert_awaited_once()
        self.assertTrue(all(r['status'] in {'success', 'submitting'} for r in results))

    async def test_read_error_does_not_turn_into_empty_list_or_refund(self):
        self.platform.applications.side_effect = RefundPlatformError('read failed')
        with self.assertRaises(RefundPlatformError): await self.prepare()
        self.platform.agree.assert_not_awaited()

    async def test_verification_only_accepts_official_https_host(self):
        self.assertTrue(valid_verification_url('https://pcauth-site.alipay.com/home?test'))
        for value in ['http://pcauth-site.alipay.com/home', 'https://pcauth-site.alipay.com.evil.test/home',
                      'https://evil.test/home', 'javascript:alert(1)', 'https://user@pcauth-site.alipay.com/home',
                      'https://pcauth-site.alipay.com:444/home']:
            self.assertFalse(valid_verification_url(value))


if __name__ == '__main__': unittest.main()
