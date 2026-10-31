"""广告升级/结算兼容性：独立MySQL库，不创建真实支付、不访问远程广告。"""
import sys
import asyncio
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, patch

from sqlalchemy import func,select,text
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.insert(0,'/app/backend-web')
from isolated_upstream_mysql import isolated_upstream_database
from common.db.advertisement_schema import ensure_advertisement_schema
from common.models.advertisement import Advertisement,AdStatus,AdType
from common.models.user import User,UserRole
from common.models.user_setting import UserSetting
from common.models.recharge_order import RechargeOrder
from common.models.fund_flow import FundFlow
from app.services.advertisement_payment_service import AdvertisementPaymentService
from app.services.advertisement_service import AdvertisementService


class AdvertisementUpgradeTests(unittest.IsolatedAsyncioTestCase):
    async def test_old_schema_migrates_twice_preserving_history_prices_and_other_data(self):
        tables=('xy_advertisements','xy_recharge_orders','xy_data_dictionaries','xy_system_settings')
        async with isolated_upstream_database(tables,legacy_ads=True) as engine:
            async with engine.begin() as conn:
                await conn.execute(text("INSERT INTO xy_system_settings (`key`,value) VALUES ('ad_price.text','12.34'),('custom.keep','保留')"))
                await conn.execute(text("INSERT INTO xy_advertisements (id,user_id,title,ad_type,status,total_amount) VALUES (1,7,'历史广告','text','approved','12.34')"))
                await conn.execute(text("INSERT INTO xy_recharge_orders (order_no,user_id,amount,order_type,status) VALUES ('legacy-test',7,'12.34','ad','paid')"))
                await ensure_advertisement_schema(conn); await ensure_advertisement_schema(conn)
                values=dict((await conn.execute(text('SELECT `key`,value FROM xy_system_settings'))).all())
                self.assertEqual(values['ad_price.text'],'12.34'); self.assertEqual(values['custom.keep'],'保留')
                self.assertEqual(values['ad_price.home_text'],''); self.assertEqual(values['ad_price.home_carousel'],'')
                ad=(await conn.execute(text('SELECT title,ad_type,status,total_amount,is_deleted FROM xy_advertisements WHERE id=1'))).one()
                self.assertEqual(tuple(ad),('历史广告','text','approved','12.34',0))
                old=(await conn.execute(text('SELECT amount,status,ad_id,ad_settled_at FROM xy_recharge_orders'))).one()
                self.assertEqual(tuple(old),('12.34','paid',None,None))
                self.assertEqual((await conn.execute(text("SELECT COUNT(*) FROM xy_data_dictionaries WHERE dict_type='advertisement_type'"))).scalar(),4)
                await conn.execute(text("INSERT INTO xy_advertisements (user_id,title,ad_type,status) VALUES (7,'首页广告','home_text','approved')"))
                self.assertEqual((await conn.execute(text('SELECT COUNT(*) FROM xy_advertisements'))).scalar(),2)


class AdvertisementIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.scope=isolated_upstream_database(('xy_advertisements','xy_recharge_orders','xy_data_dictionaries',
            'xy_users','xy_user_settings','xy_fund_flows'))
        self.engine=await self.scope.__aenter__()
        self.db=AsyncSession(self.engine,expire_on_commit=False)
        self.db.add_all([User(id=i,username=f'ad-test-{i}',email=f'ad{i}@example.invalid',password_hash='test-only',
            role=UserRole.ADMIN if i==1 else UserRole.MEMBER) for i in (1,7,8)])
        self.db.add_all([UserSetting(user_id=1,key='balance',value='100'),UserSetting(user_id=7,key='balance',value='50')])
        await self.db.commit()

    async def asyncTearDown(self):
        await self.db.close(); await self.scope.__aexit__(None,None,None)

    async def ad(self,id=1,status=AdStatus.UNPAID,deleted=False,kind=AdType.TEXT):
        ad=Advertisement(id=id,user_id=7,title=f'ad-{id}',ad_type=kind,status=status,total_amount='25.00',is_deleted=deleted)
        self.db.add(ad); await self.db.flush();return ad

    async def order(self,id=1,ad_id=1,kind='ad',status='paid'):
        order=RechargeOrder(id=id,order_no=f'test-order-{id}',user_id=7,amount='25.00',order_type=kind,status=status,ad_id=ad_id,created_at=datetime(2026,11,1))
        self.db.add(order);await self.db.flush();return order

    async def balance_and_count(self):
        self.db.expire_all()
        amount=(await self.db.execute(select(UserSetting.value).where(UserSetting.user_id==1,UserSetting.key=='balance'))).scalar_one()
        count=(await self.db.execute(select(func.count()).select_from(FundFlow))).scalar()
        return amount,count

    async def test_legacy_unlinked_paid_order_cannot_pay_for_new_same_price_ad(self):
        await self.ad(1,AdStatus.APPROVED); fresh=await self.ad(2)
        old=await self.order(ad_id=None);await self.db.commit()
        result=await AdvertisementPaymentService(self.db).poll(2,old.order_no,7)
        self.assertFalse(result.success)
        await self.db.refresh(fresh);await self.db.refresh(old)
        self.assertEqual(fresh.status,AdStatus.UNPAID);self.assertIsNone(old.ad_id)
        self.assertEqual(await self.balance_and_count(),('100',0))

    async def test_new_linked_payment_settles_only_once_across_poll_and_notifications(self):
        ad=await self.ad();order=await self.order(status='pending');await self.db.commit()
        service=AdvertisementPaymentService(self.db)
        await service.notify(order,{'total_amount':'25.00','trade_no':'fake-trade'})
        await service.notify(order,{'total_amount':'25.00','trade_no':'fake-trade'})
        result=await service.poll(1,'test-order-1',7)
        self.assertTrue(result.success)
        self.assertEqual(await self.balance_and_count(),('125.00',1))
        owner_balance=(await self.db.execute(select(UserSetting.value).where(UserSetting.user_id==7,UserSetting.key=='balance'))).scalar_one()
        self.assertEqual(owner_balance,'50')

    async def test_wrong_owner_ad_and_recharge_orders_do_not_settle(self):
        await self.ad(1);await self.ad(2);await self.order();await self.order(2,1,kind='recharge');await self.db.commit()
        service=AdvertisementPaymentService(self.db)
        for ad_id,number,owner in ((1,'test-order-1',8),(2,'test-order-1',7),(1,'test-order-2',7)):
            self.assertFalse((await service.poll(ad_id,number,owner)).success)
        self.assertEqual(await self.balance_and_count(),('100',0))

    async def test_concurrent_mysql_pollers_credit_a_linked_order_once(self):
        await self.ad();await self.order();await self.db.commit()
        async def poll():
            async with AsyncSession(self.engine,expire_on_commit=False) as db:
                return await AdvertisementPaymentService(db).poll(1,'test-order-1',7)
        results=await asyncio.gather(poll(),poll(),poll())
        self.assertTrue(all(result.success for result in results))
        self.assertEqual(await self.balance_and_count(),('125.00',1))

    async def test_amount_mismatch_rejected_and_deleted_ad_not_reactivated(self):
        ad=await self.ad(deleted=True);order=await self.order(status='pending');await self.db.commit()
        service=AdvertisementPaymentService(self.db)
        with self.assertRaises(ValueError): await service.notify(order,{'total_amount':'26.00'})
        await service.notify(order,{'total_amount':'25.00','trade_no':'fake-trade'})
        await self.db.refresh(ad)
        self.assertEqual(ad.status,AdStatus.UNPAID);self.assertTrue(ad.is_deleted)
        self.assertEqual(await self.balance_and_count(),('125.00',1))

    async def test_public_ad_placement_filters_unapproved_deleted_and_expired(self):
        await self.ad(1,AdStatus.APPROVED,kind=AdType.TEXT)
        await self.ad(2,AdStatus.APPROVED,kind=AdType.HOME_TEXT)
        await self.ad(3,AdStatus.UNPAID,kind=AdType.HOME_TEXT)
        await self.ad(4,AdStatus.APPROVED,deleted=True,kind=AdType.HOME_TEXT)
        expired=await self.ad(5,AdStatus.APPROVED,kind=AdType.HOME_TEXT);expired.expire_date=datetime(2000,1,1).date()
        await self.db.commit()
        with patch('app.services.advertisement_service.fetch_remote_public_ads',AsyncMock(return_value={'carousel':[],'text':[]})):
            service=AdvertisementService(self.db)
            home=await service.get_public('home',None);dashboard=await service.get_public('dashboard',None)
        self.assertEqual([a['id'] for a in home.data['text']],[2]);self.assertEqual([a['id'] for a in dashboard.data['text']],[1])


if __name__=='__main__':unittest.main()
