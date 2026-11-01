"""昵称快照与历史补齐回归；连接私有临时表，不触发平台请求。"""
import sys
import unittest
from datetime import datetime
from sqlalchemy import select,text
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.insert(0,'/app/backend-web')
from common.db.session import async_engine
from common.models.user import User,UserRole
from common.models.xy_account import XYAccount
from common.models.publish_log import PublishLog
from common.services.publish_log_service import PublishLogService


class PublishLogNicknameTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn=await async_engine.connect()
        for table in ('xy_publish_logs','xy_accounts','xy_users'):
            ddl=(await self.conn.execute(text(f'SHOW CREATE TABLE {table}'))).one()[1]
            await self.conn.execute(text(ddl.replace('CREATE TABLE','CREATE TEMPORARY TABLE',1)))
        fields=(await self.conn.execute(text('SHOW COLUMNS FROM xy_publish_logs'))).all()
        if 'account_nickname' not in {f[0] for f in fields}:
            await self.conn.execute(text('ALTER TABLE xy_publish_logs ADD COLUMN account_nickname VARCHAR(120) NULL'))
        self.db=AsyncSession(bind=self.conn,expire_on_commit=False)
        self.db.add_all([User(id=i,username=f'nickname-test-{i}',email=f'nick{i}@example.invalid',password_hash='test-only',
            role=UserRole.ADMIN if i==1 else UserRole.MEMBER) for i in (1,7,8)])
        self.account=XYAccount(id=100,owner_id=7,account_id='original-shop',cookie='test-only',login_method='cookie',
            metadata_json={'profile':{'nickname':'芋圆奶茶'}},remark='不是昵称的备注')
        self.db.add(self.account);await self.db.commit()

    async def asyncTearDown(self):
        await self.db.close()
        for table in ('xy_publish_logs','xy_accounts','xy_users'):
            await self.conn.execute(text(f'DROP TEMPORARY TABLE {table}'))
        await self.conn.commit();await self.conn.close();await async_engine.dispose()

    async def test_created_log_keeps_nickname_after_account_removed(self):
        log=await PublishLogService(self.db).create_log(7,'original-shop','test-only',status='success')
        await self.db.delete(self.account);await self.db.commit()
        result=await PublishLogService(self.db).list_logs(7)
        self.assertEqual(result['list'][0]['account_nickname'],'芋圆奶茶')
        self.assertEqual(result['list'][0]['account_id'],'original-shop')
        self.assertEqual(result['list'][0]['status'],'success')

    async def test_foreign_member_cannot_snapshot_another_users_nickname(self):
        await PublishLogService(self.db).create_log(8,'original-shop','test-only')
        self.assertIsNone((await PublishLogService(self.db).list_logs(8))['list'][0]['account_nickname'])

    async def test_admin_can_snapshot_authorized_cross_owner_target(self):
        await PublishLogService(self.db).create_log(1,'original-shop','test-only')
        self.assertEqual((await PublishLogService(self.db).list_logs(1))['list'][0]['account_nickname'],'芋圆奶茶')

    async def test_account_deletion_preserves_missing_snapshot_and_existing_history_state(self):
        from app.services.account_service import AccountService
        old=PublishLog(user_id=7,account_id='original-shop',title='test-only',status='unknown',
            updated_at=datetime(2026,10,1),history_cleared_at=datetime(2026,10,2))
        self.db.add(old);await self.db.commit()
        old_id=old.id
        await AccountService(self.db).delete_account(self.account)
        self.db.expunge_all()
        result=(await self.db.execute(select(PublishLog).where(PublishLog.id==old_id))).scalar_one()
        self.assertEqual(result.account_nickname,'芋圆奶茶');self.assertEqual(result.status,'unknown')
        self.assertEqual(result.updated_at,datetime(2026,10,1));self.assertEqual(result.history_cleared_at,datetime(2026,10,2))

    async def test_masked_name_not_saved_as_real_nickname(self):
        self.account.metadata_json={'profile':{'nickname':'x***8'}};await self.db.commit()
        await PublishLogService(self.db).create_log(7,'original-shop','test-only')
        self.assertIsNone((await PublishLogService(self.db).list_logs(7))['list'][0]['account_nickname'])

    async def test_actual_logs_route_returns_snapshot_and_honors_cleared_history(self):
        from types import SimpleNamespace
        from app.api.routes.product_publish import list_publish_logs
        await PublishLogService(self.db).create_log(7,'original-shop','visible-test',status='success')
        hidden=PublishLog(user_id=7,account_id='original-shop',title='hidden-test',status='success',history_cleared_at=datetime(2026,10,2))
        self.db.add(hidden);await self.db.commit()
        await self.db.delete(self.account);await self.db.commit()
        response=await list_publish_logs(page=1,page_size=20,account_id=None,status=None,
            current_user=SimpleNamespace(id=7,role=UserRole.MEMBER),session=self.db)
        self.assertEqual(response.data['total'],1)
        self.assertEqual(response.data['list'][0]['account_nickname'],'芋圆奶茶')

    async def test_batch_registration_and_legacy_single_path_also_keep_snapshot(self):
        from app.services.batch_publish_service import BatchPublishService
        from app.services.publish_execution_service import PublishLogService as WebLogService
        await BatchPublishService(self.db).register(7,'test-nick-batch',['original-shop'],[{'id':1,'title':'batch-test','price':'1.00','description':'text'}])
        await WebLogService(self.db).create_log(7,'original-shop','single-test')
        await self.db.delete(self.account);await self.db.commit()
        data=(await PublishLogService(self.db).list_logs(7))['list']
        self.assertEqual(len(data),2);self.assertTrue(all(row['account_nickname']=='芋圆奶茶' for row in data))


if __name__=='__main__':unittest.main()
