"""上游个人Token配置兼容验证：私有临时表及模拟远程响应，不调用真实接口。"""
import sys
import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from loguru import logger
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.insert(0,'/app/backend-web')
from common.db.session import async_engine
from common.models.user import User
from common.models.user_setting import UserSetting
from common.models.system_setting import SystemSetting
from common.models.xy_account import XYAccount
from common.schemas.system_setting import RemoteTokenTestRequest
from common.services import remote_token_api as token
from app.services import token_remote_test_service as remote_test
from app.services.user_token_setting_service import UserTokenSettingService


class TokenLoggingTests(unittest.IsolatedAsyncioTestCase):
    async def test_remote_failure_log_omits_request_response_credentials_and_url_secrets(self):
        messages=[]; sink=logger.add(lambda record:messages.append(str(record)),format='{message}')
        try:
            token._log_remote_token_failure('https://fake-user:fake-pass@example.invalid/api?key=fake-query',
                'fake-key-private','fake-cookie-private',status_code=503,
                response_headers={'Set-Cookie':'fake-response-cookie'},
                response_body={'token':'fake-response-token','message':'fake-cookie-private'},
                error=RuntimeError('fake-key-private'))
        finally: logger.remove(sink)
        output=''.join(messages)
        for secret in ('fake-user','fake-pass','fake-query','fake-key-private','fake-cookie-private',
                'fake-response-cookie','fake-response-token'):
            self.assertNotIn(secret,output)
        self.assertIn('503',output); self.assertIn('example.invalid',output); self.assertIn('RuntimeError',output)

    async def test_connectivity_test_logs_no_key_or_returned_token(self):
        messages=[]; sink=logger.add(lambda record:messages.append(str(record)),format='{message}')
        response=token.RemoteTokenResult(False,'Cookie不能为空',{'success':False,'token':'fake-return-token'},200,0.1)
        try:
            with patch.object(remote_test,'request_remote_xianyu_token',AsyncMock(return_value=response)), \
                    patch.object(remote_test,'record_remote_token_risk_log',AsyncMock()):
                result=await remote_test.test_token_remote_settings(RemoteTokenTestRequest(
                    remote_url='https://example.invalid/token?key=fake-query',remote_secret_key='fake-key-private'),
                    SimpleNamespace(id=7,username='test-only'),scene='个人设置')
        finally: logger.remove(sink)
        self.assertTrue(result.success)
        for secret in ('fake-key-private','fake-return-token','fake-query'):
            self.assertNotIn(secret,''.join(messages))

    async def test_test_exception_does_not_log_or_return_reflected_secret(self):
        messages=[]; sink=logger.add(lambda record:messages.append(str(record)),format='{message}')
        try:
            with patch.object(remote_test,'request_remote_xianyu_token',AsyncMock(side_effect=RuntimeError('fake-key-private'))), \
                    patch.object(remote_test,'record_remote_token_risk_log',AsyncMock()):
                result=await remote_test.test_token_remote_settings(RemoteTokenTestRequest(
                    remote_url='https://example.invalid/token',remote_secret_key='fake-key-private'),
                    SimpleNamespace(id=7,username='test-only'),scene='个人设置')
        finally: logger.remove(sink)
        self.assertFalse(result.success)
        self.assertNotIn('fake-key-private',''.join(messages)); self.assertNotIn('fake-key-private',result.message)

    async def test_test_risk_message_does_not_persist_reflected_key(self):
        response=token.RemoteTokenResult(False,'密钥无效 fake-key-private',{'success':False},403,0.1)
        with patch.object(remote_test,'request_remote_xianyu_token',AsyncMock(return_value=response)), \
                patch.object(remote_test,'record_remote_token_risk_log',AsyncMock()) as record:
            result=await remote_test.test_token_remote_settings(RemoteTokenTestRequest(
                remote_url='https://example.invalid/token',remote_secret_key='fake-key-private'),
                SimpleNamespace(id=7,username='test-only'),scene='个人设置')
        self.assertFalse(result.success)
        self.assertNotIn('fake-key-private',record.call_args.kwargs['message'])
        self.assertNotIn('fake-key-private',result.message)

    async def test_personal_save_database_error_does_not_log_credentials(self):
        db=AsyncMock();db.execute.side_effect=RuntimeError('fake-key-private')
        messages=[];sink=logger.add(lambda record:messages.append(str(record)),format='{message}')
        try:
            with self.assertRaises(RuntimeError):
                await UserTokenSettingService(db,7).save_settings(RemoteTokenTestRequest(
                    remote_url='https://example.invalid/token',remote_secret_key='fake-key-private'))
        finally: logger.remove(sink)
        self.assertNotIn('fake-key-private',''.join(messages))


class PersonalTokenDatabaseTests(unittest.IsolatedAsyncioTestCase):
    tables=('xy_accounts','xy_user_settings','xy_system_settings','xy_users')

    async def asyncSetUp(self):
        self.conn=await async_engine.connect()
        for table in self.tables:
            ddl=(await self.conn.execute(text(f'SHOW CREATE TABLE {table}'))).one()[1]
            await self.conn.execute(text(ddl.replace('CREATE TABLE','CREATE TEMPORARY TABLE',1)))
        self.db=AsyncSession(bind=self.conn,expire_on_commit=False)
        self.db.add_all([User(id=i,username=f'test-user-{i}',email=f'user{i}@example.invalid',password_hash='test-only') for i in (7,8)])
        self.db.add_all([XYAccount(owner_id=owner,account_id=shop,cookie='test-only',login_method='cookie')
                        for owner,shop in ((7,'shop-A'),(8,'shop-B'))])
        self.db.add_all([SystemSetting(key=token.TOKEN_REMOTE_URL_SETTING_KEY,value='https://system.example.invalid'),
            SystemSetting(key=token.TOKEN_REMOTE_SECRET_KEY_SETTING_KEY,value='system-test-key'),
            UserSetting(user_id=8,key=token.TOKEN_REMOTE_URL_SETTING_KEY,value='https://owner8.example.invalid'),
            UserSetting(user_id=8,key=token.TOKEN_REMOTE_SECRET_KEY_SETTING_KEY,value='owner8-test-key')])
        await self.db.commit()

    async def asyncTearDown(self):
        await self.db.close()
        for table in self.tables:
            await self.conn.execute(text(f'DROP TEMPORARY TABLE {table}'))
        await self.conn.commit(); await self.conn.close(); await async_engine.dispose()

    @asynccontextmanager
    async def session_factory(self):
        yield self.db

    async def test_owner_only_atomic_save_and_read_preserves_other_user_and_system(self):
        service=UserTokenSettingService(self.db,7)
        saved=await service.save_settings(RemoteTokenTestRequest(remote_url='https://owner7.example.invalid',remote_secret_key='owner7-test-key'))
        self.assertTrue(saved.success)
        self.assertEqual((await service.get_settings()).data,{'remote_url':'https://owner7.example.invalid','remote_secret_key':'owner7-test-key'})
        self.assertEqual((await UserTokenSettingService(self.db,8).get_settings()).data['remote_secret_key'],'owner8-test-key')
        system=(await self.db.execute(select(SystemSetting.value).where(SystemSetting.key==token.TOKEN_REMOTE_SECRET_KEY_SETTING_KEY))).scalar_one()
        self.assertEqual(system,'system-test-key')
        invalid=await service.save_settings(RemoteTokenTestRequest(remote_url='not-a-url',remote_secret_key='changed'))
        self.assertFalse(invalid.success)
        self.assertEqual((await service.get_settings()).data['remote_secret_key'],'owner7-test-key')

    async def test_account_configuration_isolated_and_empty_personal_uses_system(self):
        first=await token._query_remote_token_settings('shop-A',self.session_factory)
        second=await token._query_remote_token_settings('shop-B',self.session_factory)
        self.assertEqual((first.url,first.secret_key,first.owner_id),('https://system.example.invalid','system-test-key',7))
        self.assertEqual((second.url,second.secret_key,second.owner_id),('https://owner8.example.invalid','owner8-test-key',8))
        self.db.add(UserSetting(user_id=7,key=token.TOKEN_REMOTE_URL_SETTING_KEY,value='https://partial.example.invalid'))
        await self.db.commit()
        partial=await token._query_remote_token_settings('shop-A',self.session_factory)
        self.assertEqual((partial.url,partial.secret_key,partial.source),('https://partial.example.invalid','','个人设置'))
        self.assertIsNotNone(token.validate_remote_token_settings(partial.url,partial.secret_key))

    async def test_unknown_account_or_database_error_never_borrows_system_configuration(self):
        with self.assertRaises(ValueError): await token._query_remote_token_settings('missing-shop',self.session_factory)
        @asynccontextmanager
        async def broken():
            raise RuntimeError('test database unavailable')
            yield
        with self.assertRaises(RuntimeError): await token._query_remote_token_settings('shop-A',broken)


if __name__=='__main__': unittest.main()
