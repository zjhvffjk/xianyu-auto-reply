"""幂等补齐发布昵称快照，保留历史结果、清空状态及原有时间。"""
from sqlalchemy import text


async def ensure_publish_account_identity_schema(conn):
    exists=(await conn.execute(text("SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='xy_publish_logs' AND COLUMN_NAME='account_nickname'"))).scalar()
    if not exists:
        await conn.execute(text("ALTER TABLE xy_publish_logs ADD COLUMN account_nickname VARCHAR(120) NULL COMMENT '发布账号昵称快照'"))
    await conn.execute(text("""
        UPDATE xy_publish_logs AS logs
        JOIN xy_accounts AS accounts ON accounts.account_id=logs.account_id AND accounts.owner_id=logs.user_id
        SET logs.account_nickname=LEFT(TRIM(JSON_UNQUOTE(JSON_EXTRACT(accounts.metadata,'$.profile.nickname'))),120),
            logs.updated_at=logs.updated_at
        WHERE (logs.account_nickname IS NULL OR logs.account_nickname='')
          AND JSON_TYPE(JSON_EXTRACT(accounts.metadata,'$.profile.nickname'))='STRING'
          AND TRIM(JSON_UNQUOTE(JSON_EXTRACT(accounts.metadata,'$.profile.nickname')))<>''
          AND JSON_UNQUOTE(JSON_EXTRACT(accounts.metadata,'$.profile.nickname')) NOT LIKE '%*%'
    """))
