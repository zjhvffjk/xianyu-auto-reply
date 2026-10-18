"""定时发布任务表的幂等建表与字段迁移。"""
from __future__ import annotations

from datetime import datetime

from loguru import logger
from sqlalchemy import text


SCHEDULED_PUBLISH_TABLE_DDL = {
    "xy_scheduled_publish_tasks": """
        CREATE TABLE IF NOT EXISTS xy_scheduled_publish_tasks (
            id BIGINT PRIMARY KEY AUTO_INCREMENT,
            user_id BIGINT NOT NULL,
            material_ids JSON NOT NULL,
            account_ids JSON NOT NULL,
            start_at DATETIME NOT NULL,
            interval_seconds INT NOT NULL DEFAULT 300,
            status VARCHAR(24) NOT NULL DEFAULT 'pending',
            next_index INT NOT NULL DEFAULT 0,
            next_run_at DATETIME NULL,
            total_count INT NOT NULL DEFAULT 0,
            success_count INT NOT NULL DEFAULT 0,
            failed_count INT NOT NULL DEFAULT 0,
            last_error TEXT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            KEY idx_sched_pub_user_status (user_id, status),
            KEY idx_sched_pub_due (status, next_run_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
}

SCHEDULED_PUBLISH_COLUMNS = {
    "xy_scheduled_publish_tasks": {
        "material_ids": "JSON NOT NULL",
        "account_ids": "JSON NOT NULL",
        "start_at": "DATETIME NOT NULL",
        "interval_seconds": "INT NOT NULL DEFAULT 300",
        "status": "VARCHAR(24) NOT NULL DEFAULT 'pending'",
        "next_index": "INT NOT NULL DEFAULT 0",
        "next_run_at": "DATETIME NULL",
        "total_count": "INT NOT NULL DEFAULT 0",
        "success_count": "INT NOT NULL DEFAULT 0",
        "failed_count": "INT NOT NULL DEFAULT 0",
        "last_error": "TEXT NULL",
    },
}

SCHEDULED_PUBLISH_INDEXES = {
    "xy_scheduled_publish_tasks": {
        "idx_sched_pub_user_status": "(user_id, status)",
        "idx_sched_pub_due": "(status, next_run_at)",
    },
}


async def ensure_scheduled_publish_schema(conn) -> None:
    """创建定时发布任务表并幂等补齐字段、索引。

    Args:
        conn: 数据库连接。
    """
    for table_name, ddl in SCHEDULED_PUBLISH_TABLE_DDL.items():
        await conn.execute(text(ddl))

    for table_name, columns in SCHEDULED_PUBLISH_COLUMNS.items():
        for column_name, column_definition in columns.items():
            exists = await conn.execute(
                text("""SELECT COUNT(*) FROM information_schema.COLUMNS
                       WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table_name
                       AND COLUMN_NAME = :column_name"""),
                {"table_name": table_name, "column_name": column_name},
            )
            if not exists.scalar():
                await conn.execute(
                    text(f"ALTER TABLE `{table_name}` ADD COLUMN `{column_name}` {column_definition}")
                )
                logger.info("定时发布表补齐字段: {}.{}", table_name, column_name)

    for table_name, indexes in SCHEDULED_PUBLISH_INDEXES.items():
        for index_name, index_definition in indexes.items():
            exists = await conn.execute(
                text("""SELECT COUNT(*) FROM information_schema.STATISTICS
                       WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table_name
                       AND INDEX_NAME = :index_name"""),
                {"table_name": table_name, "index_name": index_name},
            )
            if not exists.scalar():
                await conn.execute(
                    text(f"ALTER TABLE `{table_name}` ADD INDEX `{index_name}` {index_definition}")
                )
                logger.info("定时发布表补齐索引: {}.{}", table_name, index_name)
