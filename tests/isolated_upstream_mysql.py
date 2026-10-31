"""上游升级回归的独立MySQL测试库，创建及清理仅限随机测试名称。"""
from contextlib import asynccontextmanager
import re
from uuid import uuid4

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool
from common.db.session import async_engine


@asynccontextmanager
async def isolated_upstream_database(tables, *, legacy_ads=False):
    name='xy_upstream_test_'+uuid4().hex
    created=False; engine=None
    try:
        async with async_engine.begin() as connection:
            ddls=[]
            for table in tables:
                assert re.fullmatch(r'xy_[a-z_]+',table)
                ddl=(await connection.exec_driver_sql(f'SHOW CREATE TABLE `{table}`')).one()[1]
                if legacy_ads:
                    ddl='\n'.join(line for line in ddl.splitlines() if not re.match(r'\s*`(is_deleted|ad_id|ad_settled_at)` ',line))
                    ddl=re.sub(r"(`ad_type` )enum\([^\n]+?\)",r"\1enum('carousel','text')",ddl)
                ddls.append(ddl)
            await connection.exec_driver_sql(f'CREATE DATABASE `{name}` CHARACTER SET utf8mb4')
            created=True
        engine=create_async_engine(async_engine.url.set(database=name),echo=False,poolclass=NullPool)
        async with engine.begin() as connection:
            for ddl in ddls: await connection.exec_driver_sql(ddl)
        yield engine
    finally:
        if engine: await engine.dispose()
        if created:
            assert re.fullmatch(r'xy_upstream_test_[0-9a-f]{32}',name)
            async with async_engine.begin() as connection:
                await connection.exec_driver_sql(f'DROP DATABASE `{name}`')
        await async_engine.dispose()
