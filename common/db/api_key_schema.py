"""对外 API 秘钥表（xy_api_keys）的幂等建表与字段迁移。

与 common/db/auto_relist_schema.py 保持同一范式：
先执行 CREATE TABLE IF NOT EXISTS，再逐字段/索引检查后补齐，
保证老库升级与全新安装都能得到一致的表结构。
"""
from __future__ import annotations

from loguru import logger
from sqlalchemy import text


API_KEY_TABLE_DDL = {
    "xy_api_keys": """
        CREATE TABLE IF NOT EXISTS xy_api_keys (
            id BIGINT PRIMARY KEY AUTO_INCREMENT,
            key_value VARCHAR(64) NOT NULL COMMENT '对外秘钥（明文，需可查看以便发放）',
            name VARCHAR(120) NOT NULL DEFAULT '' COMMENT '备注：发给谁 / 用途',
            status VARCHAR(20) NOT NULL DEFAULT 'active' COMMENT 'active / disabled',
            daily_quota INT NOT NULL DEFAULT 0 COMMENT '每日调用上限，0=不限（M2 生效）',
            expire_at DATETIME NULL COMMENT '过期时间，NULL=永不过期',
            last_used_at DATETIME NULL COMMENT '最后调用时间',
            total_calls BIGINT NOT NULL DEFAULT 0 COMMENT '累计调用次数',
            owner_user_id BIGINT NOT NULL DEFAULT 0 COMMENT '发放人（本系统用户ID，0=系统）',
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uk_api_key_value (key_value),
            KEY idx_api_key_status (status)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='对外API秘钥表'
    """,
}

API_KEY_COLUMNS = {
    "key_value": "VARCHAR(64) NOT NULL DEFAULT '' COMMENT '对外秘钥（明文，需可查看以便发放）'",
    "name": "VARCHAR(120) NOT NULL DEFAULT '' COMMENT '备注：发给谁 / 用途'",
    "status": "VARCHAR(20) NOT NULL DEFAULT 'active' COMMENT 'active / disabled'",
    "daily_quota": "INT NOT NULL DEFAULT 0 COMMENT '每日调用上限，0=不限（M2 生效）'",
    "expire_at": "DATETIME NULL COMMENT '过期时间，NULL=永不过期'",
    "last_used_at": "DATETIME NULL COMMENT '最后调用时间'",
    "total_calls": "BIGINT NOT NULL DEFAULT 0 COMMENT '累计调用次数'",
    "owner_user_id": "BIGINT NOT NULL DEFAULT 0 COMMENT '发放人（本系统用户ID，0=系统）'",
    "created_at": "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
    "updated_at": "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP",
}

# 索引名 -> 索引定义；UNIQUE 前缀由 ensure_api_key_schema 转成 ADD UNIQUE KEY
API_KEY_INDEXES = {
    "uk_api_key_value": "UNIQUE (key_value)",
    "idx_api_key_status": "(status)",
}


async def ensure_api_key_schema(conn) -> None:
    """创建对外 API 秘钥表并幂等补齐字段、索引。

    Args:
        conn: 数据库连接（调用方置于 ddl_connection() 上下文内）。
    """
    for ddl in API_KEY_TABLE_DDL.values():
        await conn.execute(text(ddl))

    for column_name, column_definition in API_KEY_COLUMNS.items():
        exists = await conn.execute(
            text("""SELECT COUNT(*) FROM information_schema.COLUMNS
                   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'xy_api_keys'
                   AND COLUMN_NAME = :column_name"""),
            {"column_name": column_name},
        )
        if not exists.scalar():
            await conn.execute(
                text(f"ALTER TABLE `xy_api_keys` ADD COLUMN `{column_name}` {column_definition}")
            )
            logger.info("对外API秘钥表补齐字段: {}", column_name)

    for index_name, index_definition in API_KEY_INDEXES.items():
        exists = await conn.execute(
            text("""SELECT COUNT(*) FROM information_schema.STATISTICS
                   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'xy_api_keys'
                   AND INDEX_NAME = :index_name"""),
            {"index_name": index_name},
        )
        if not exists.scalar():
            add_clause = "ADD UNIQUE KEY" if index_definition.startswith("UNIQUE") else "ADD KEY"
            definition = (
                index_definition.replace("UNIQUE ", "", 1)
                if index_definition.startswith("UNIQUE")
                else index_definition
            )
            await conn.execute(
                text(f"ALTER TABLE `xy_api_keys` {add_clause} `{index_name}` {definition}")
            )
            logger.info("对外API秘钥表补齐索引: {}", index_name)


__all__ = [
    "API_KEY_COLUMNS",
    "API_KEY_INDEXES",
    "API_KEY_TABLE_DDL",
    "ensure_api_key_schema",
]
