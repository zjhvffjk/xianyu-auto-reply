"""真实MySQL隔离验证：只使用负数测试用户，不调用闲鱼。"""
import sys
import unittest
from datetime import datetime
from uuid import uuid4
from types import SimpleNamespace
from sqlalchemy import delete, select
sys.path.insert(0, '/app/backend-web')
from common.db.session import async_engine, async_session_maker
from common.models.product_material import ProductMaterial
from common.models.publish_log import PublishLog
from app.services.material_category_service import MaterialCategoryService
from app.services.material_publish_summary import latest_material_publications

OWNER = -2026102502
TARGET = dict(cat_id='50023914', cat_name='其他闲置', channel_cat_id='201459411',
              channel_cat_name='其他闲置', tb_cat_id='50014945', path=[])


class MaterialCategoryHistoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.ids = []
        async with async_session_maker() as s:
            for owner in (OWNER, OWNER-1):
                m = ProductMaterial(user_id=owner, title='test-only-'+str(uuid4()), description='保留原文',
                    price=1, quantity=2, platform_category_id='50023914', platform_channel_category_id='126860387',
                    platform_category_name='明星小卡', platform_attributes=[dict(property_id='test', value_id='old')])
                s.add(m); await s.flush(); self.ids.append(m.id)
            await s.commit()

    async def asyncTearDown(self):
        async with async_session_maker() as s:
            await s.execute(delete(PublishLog).where(PublishLog.material_id.in_(self.ids), PublishLog.user_id.in_([OWNER, OWNER-1])))
            await s.execute(delete(ProductMaterial).where(ProductMaterial.id.in_(self.ids), ProductMaterial.user_id.in_([OWNER, OWNER-1])))
            await s.commit()
        await async_engine.dispose()

    async def entry(self, s):
        rows = await MaterialCategoryService(s).preview([self.ids[0]], OWNER, mode='replace')
        return dict(id=self.ids[0], candidate=TARGET, expected_category_token=rows[0]['category_token'])

    async def test_fill_still_skips_complete_category(self):
        async with async_session_maker() as s:
            result = await MaterialCategoryService(s).save([dict(id=self.ids[0], candidate=TARGET)], OWNER)
            self.assertEqual(result[0]['status'], 'skipped')

    async def test_replace_same_cat_different_channel_clears_old_attributes(self):
        async with async_session_maker() as s:
            entry = await self.entry(s)
            result = await MaterialCategoryService(s).save([entry], OWNER, mode='replace')
            self.assertEqual(result[0]['status'], 'saved')
            m = await s.get(ProductMaterial, self.ids[0])
            self.assertEqual(m.platform_channel_category_id, TARGET['channel_cat_id'])
            self.assertEqual(m.platform_attributes, [])
            self.assertEqual((m.description, m.quantity), ('保留原文', 2))

    async def test_replace_requires_preview_and_rejects_stale_category(self):
        async with async_session_maker() as s:
            svc = MaterialCategoryService(s)
            result = await svc.save([dict(id=self.ids[0], candidate=TARGET)], OWNER, mode='replace')
            self.assertEqual(result[0]['status'], 'conflict')
            entry = await self.entry(s)
            m = await s.get(ProductMaterial, self.ids[0]); m.platform_attributes=[]; await s.commit()
            result = await svc.save([entry], OWNER, mode='replace')
            self.assertEqual(result[0]['status'], 'conflict')

    async def test_same_identity_keeps_attributes(self):
        async with async_session_maker() as s:
            entry = await self.entry(s)
            entry['candidate'] = dict(cat_id='50023914', channel_cat_id='126860387', cat_name='明星小卡', path=[])
            result = await MaterialCategoryService(s).save([entry], OWNER, mode='replace')
            self.assertEqual(result[0]['status'], 'saved')
            self.assertTrue((await s.get(ProductMaterial, self.ids[0])).platform_attributes)

    async def test_other_owner_cannot_preview_or_replace(self):
        async with async_session_maker() as s:
            svc = MaterialCategoryService(s)
            self.assertEqual((await svc.preview([self.ids[1]], OWNER, mode='replace'))[0]['status'], 'failed')
            result = await svc.save([dict(id=self.ids[1], candidate=TARGET)], OWNER, mode='replace')
            self.assertEqual(result[0]['status'], 'failed')

    async def test_latest_log_is_owner_scoped_and_links_are_canonical(self):
        async with async_session_maker() as s:
            for user, status, item in [(OWNER, 'failed', None), (OWNER, 'success', '123456'), (OWNER-1, 'failed', None)]:
                s.add(PublishLog(user_id=user, material_id=self.ids[0], account_id='test-only',
                    title='test-only', status=status, item_id=item, item_url='javascript:bad',
                    error_message='test-failure', created_at=datetime(2099,1,1)))
            await s.commit()
            result = await latest_material_publications(s, [dict(id=self.ids[0], user_id=OWNER)])
            self.assertEqual(result[self.ids[0]]['status'], 'success')
            self.assertEqual(result[self.ids[0]]['item_url'], 'https://www.goofish.com/item?id=123456')
            self.assertTrue(result[self.ids[0]]['created_at'].endswith('+08:00'))

    async def test_latest_failure_retained_and_no_log_is_absent(self):
        async with async_session_maker() as s:
            self.assertEqual(await latest_material_publications(s, [dict(id=self.ids[0], user_id=OWNER)]), {})
            s.add(PublishLog(user_id=OWNER, material_id=self.ids[0], account_id='test-only', title='test-only',
                status='failed', error_message='平台不支持网页发布', item_url='https://evil.invalid'))
            await s.commit()
            result = await latest_material_publications(s, [dict(id=self.ids[0], user_id=OWNER)])
            self.assertEqual(result[self.ids[0]]['error_message'], '平台不支持网页发布')
            self.assertIsNone(result[self.ids[0]]['item_url'])

    async def test_route_contract_requires_explicit_replace_mode_and_preview(self):
        from app.api.routes.product_publish import (MaterialCategoryPreviewRequest,
            MaterialCategorySaveRequest, preview_material_categories, confirm_material_categories)
        from common.models.user import UserRole
        user = SimpleNamespace(id=OWNER, role=UserRole.MEMBER)
        async with async_session_maker() as s:
            preview = await preview_material_categories(MaterialCategoryPreviewRequest(ids=[self.ids[0]], mode='replace'), user, s)
            row = preview.data['results'][0]
            request = MaterialCategorySaveRequest(mode='replace', entries=[dict(id=self.ids[0], candidate=TARGET,
                expected_category_token=row['category_token'])])
            result = await confirm_material_categories(request, user, s)
            self.assertEqual(result.data['results'][0]['status'], 'saved')

    async def test_list_route_returns_latest_summary_and_only_owned_materials(self):
        from app.api.routes.product_publish import list_materials
        from common.models.user import UserRole
        async with async_session_maker() as s:
            s.add(PublishLog(user_id=OWNER, material_id=self.ids[0], account_id='test-only', title='test-only',
                status='failed', error_message='仅供测试'))
            await s.commit()
            result = await list_materials(page=1, page_size=20, title=None, category=None, condition=None,
                platform_category_id=None, source_account_id=None, own_only=True, include_unlinked=False,
                current_user=SimpleNamespace(id=OWNER, role=UserRole.MEMBER), session=s)
            self.assertTrue(result.success)
            self.assertEqual(len(result.data['list']), 1)
            self.assertEqual(result.data['list'][0]['latest_publication']['error_message'], '仅供测试')


if __name__ == '__main__': unittest.main()
