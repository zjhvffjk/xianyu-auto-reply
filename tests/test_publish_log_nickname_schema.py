"""昵称快照升级回归：独立测试库，重复执行并保留原有历史状态。"""
import unittest
from sqlalchemy import text
from isolated_upstream_mysql import isolated_upstream_database
from common.db.publish_account_identity_schema import ensure_publish_account_identity_schema


class PublishLogNicknameSchemaTests(unittest.IsolatedAsyncioTestCase):
    async def test_upgrade_is_idempotent_and_backfills_only_owned_real_nicknames(self):
        async with isolated_upstream_database(('xy_accounts', 'xy_publish_logs')) as engine:
            async with engine.begin() as conn:
                columns=(await conn.execute(text('SHOW COLUMNS FROM xy_publish_logs'))).all()
                if 'account_nickname' in {column[0] for column in columns}:
                    await conn.execute(text('ALTER TABLE xy_publish_logs DROP COLUMN account_nickname'))
                await conn.execute(text("""
                    INSERT INTO xy_accounts (owner_id,account_id,cookie,login_method,metadata)
                    VALUES (7,'real-shop','test-only','cookie','{"profile":{"nickname":"芋圆奶茶"}}'),
                           (7,'masked-shop','test-only','cookie','{"profile":{"nickname":"x***8"}}')
                """))
                await conn.execute(text("""
                    INSERT INTO xy_publish_logs (user_id,account_id,title,status,updated_at,history_cleared_at)
                    VALUES (7,'real-shop','owned','unknown','2026-10-01','2026-10-02'),
                           (8,'real-shop','foreign','success','2026-10-01',NULL),
                           (7,'masked-shop','masked','success','2026-10-01',NULL),
                           (7,'removed-shop','missing','success','2026-10-01',NULL)
                """))
                await ensure_publish_account_identity_schema(conn)
                await conn.execute(text("""INSERT INTO xy_publish_logs (user_id,account_id,title,status,account_nickname)
                    VALUES (7,'real-shop','existing','success','发布时的昵称')"""))
                await ensure_publish_account_identity_schema(conn)
                rows=(await conn.execute(text('SELECT title,account_nickname,status,updated_at,history_cleared_at FROM xy_publish_logs ORDER BY id'))).all()
                by_title={row[0]:row for row in rows}
                self.assertEqual(by_title['owned'][1],'芋圆奶茶')
                self.assertEqual(by_title['owned'][2],'unknown')
                self.assertEqual(str(by_title['owned'][3]),'2026-10-01 00:00:00')
                self.assertEqual(str(by_title['owned'][4]),'2026-10-02 00:00:00')
                for title in ('foreign','masked','missing'):
                    self.assertIsNone(by_title[title][1])
                self.assertEqual(by_title['existing'][1],'发布时的昵称')


if __name__=='__main__':
    unittest.main()
