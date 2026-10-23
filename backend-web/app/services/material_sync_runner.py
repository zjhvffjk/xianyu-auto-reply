"""
素材库批量任务后台执行器（从商品同步 / 刷新价格库存）

功能：
1. 任务创建后由 BackgroundTasks 拉起，自建数据库会话跑完整循环
   （不能复用请求会话），前端只负责发起与轮询进度
2. 每批处理完把进度写回任务表：页面刷新、关标签页、服务重启后
   进度不丢，重新打开页面可继续跟踪
3. 每批开始前检查取消标记；命中风控/无进展时自动收尾，剩余留给下次
"""
from __future__ import annotations

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from common.db.session import async_session_maker
from common.models.material_sync_task import (
    TASK_TYPE_PRICE_STOCK,
    TASK_TYPE_SYNC,
    MaterialSyncTask,
)
from common.utils.time_utils import get_beijing_now_naive

from app.services.material_sync_service import (
    DEFAULT_BATCH_LIMIT,
    MaterialSyncService,
)
from app.services.material_sync_task_service import MaterialSyncTaskService

# 单轮循环的绝对上限：即使每批都有进展，也不允许无限跑（防异常死循环）
MAX_ROUNDS = 500


async def _run_sync_loop(
    session: AsyncSession,
    task_service: MaterialSyncTaskService,
    sync_service: MaterialSyncService,
    task: MaterialSyncTask,
) -> tuple[bool, str]:
    """执行「从商品同步」循环。

    Args:
        session: 数据库会话。
        task_service: 任务服务。
        sync_service: 素材同步服务。
        task: 任务行。

    Returns:
        (是否正常跑完, 收尾说明)。False 表示被取消或异常中止。
    """
    for _ in range(MAX_ROUNDS):
        if await task_service.is_canceled(task.task_id):
            logger.info(f"【素材任务】任务已被取消，停止执行 task={task.task_id}")
            return False, "用户已取消任务"

        batch = await sync_service.sync_batch(
            user_id=task.owner_id,
            owner_scope=task.owner_scope,
            limit=DEFAULT_BATCH_LIMIT,
            account_pk=task.account_pk,
            # 任务创建时选定的平台状态（在售/已下架/已售罄）；老任务为 NULL = 不限
            platform_status=task.platform_status,
        )
        await task_service.update_progress(
            task.task_id,
            {
                "processed": batch.get("processed") or 0,
                "created": batch.get("created") or 0,
                "revived": batch.get("revived") or 0,
                "failed": batch.get("failed") or 0,
                "skipped": batch.get("skipped") or 0,
                "remaining": batch.get("remaining") or 0,
            },
        )

        if batch.get("aborted"):
            return False, "检测到账号风控信号，已停止同步，稍后可再试"
        if int(batch.get("remaining") or 0) <= 0:
            return True, ""
        # 本批毫无进展（不新增也不失败）说明剩余条目无法自动处理，停止避免空转
        if not (batch.get("created") or 0) and not (batch.get("failed") or 0):
            return False, "剩余商品无法自动同步（多为缺少图片或账号详情不可用）"
    return False, "循环轮数已达上限，已停止，请稍后重试"


async def _run_price_stock_loop(
    session: AsyncSession,
    task_service: MaterialSyncTaskService,
    sync_service: MaterialSyncService,
    task: MaterialSyncTask,
) -> tuple[bool, str]:
    """执行「刷新价格/库存」循环。"""
    for _ in range(MAX_ROUNDS):
        if await task_service.is_canceled(task.task_id):
            logger.info(f"【素材任务】任务已被取消，停止执行 task={task.task_id}")
            return False, "用户已取消任务"

        batch = await sync_service.refresh_price_stock_batch(
            user_id=task.owner_id,
            owner_scope=task.owner_scope,
            limit=DEFAULT_BATCH_LIMIT,
        )
        await task_service.update_progress(
            task.task_id,
            {
                "processed": batch.get("processed") or 0,
                "updated": batch.get("updated") or 0,
                "failed": batch.get("failed") or 0,
                "remaining": batch.get("remaining") or 0,
            },
        )

        if batch.get("aborted"):
            return False, "检测到账号风控信号，已停止刷新，稍后可再试"
        if int(batch.get("remaining") or 0) <= 0:
            return True, ""
        if not (batch.get("updated") or 0) and not (batch.get("failed") or 0):
            return False, "剩余素材无法自动刷新（多为缺少源商品或账号详情不可用）"
    return False, "循环轮数已达上限，已停止，请稍后重试"


async def run_material_sync_task(task_id: str) -> None:
    """后台任务入口：执行一次素材库批量任务。

    自建数据库会话（不能复用请求会话），无论成功失败都会给任务收尾状态。

    Args:
        task_id: 任务ID（UUID）。
    """
    async with async_session_maker() as session:
        task_service = MaterialSyncTaskService(session)
        sync_service = MaterialSyncService(session)
        task = await task_service.get_task(task_id)
        if task is None:
            logger.warning(f"【素材任务】任务不存在，已跳过 task={task_id}")
            return

        if not await task_service.mark_task_running(task_id):
            # 任务可能在执行器真正启动前已被取消，不能覆盖取消状态并继续跑
            logger.info(f"【素材任务】任务已被取消或状态已变，跳过执行 task={task_id}")
            return

        logger.info(
            f"【素材任务】开始执行 task={task_id} 类型={task.task_type} "
            f"账号={task.account_pk or '全部'} 缺口={task.total_missing}"
        )

        finished_note = ""
        try:
            if task.task_type == TASK_TYPE_SYNC:
                ok, note = await _run_sync_loop(session, task_service, sync_service, task)
            elif task.task_type == TASK_TYPE_PRICE_STOCK:
                ok, note = await _run_price_stock_loop(
                    session, task_service, sync_service, task
                )
            else:
                logger.error(f"【素材任务】未知任务类型 task={task_id} type={task.task_type}")
                await task_service.finish_task(task_id, f"未知任务类型：{task.task_type}")
                return
            finished_note = "" if ok else (note or "任务未执行完")
        except Exception as exc:  # noqa: BLE001 - 任何异常都要给任务收尾
            logger.error(f"【素材任务】任务执行异常 task={task_id}：{exc}")
            # 先回滚，避免会话处于待回滚状态导致收尾写库继续失败
            await session.rollback()
            finished_note = f"任务执行异常：{exc}"

        try:
            await task_service.finish_task(task_id, finished_note or None)
        except Exception as finish_exc:  # noqa: BLE001 - 收尾失败只记日志
            logger.error(f"【素材任务】任务收尾失败 task={task_id}：{finish_exc}")
            await session.rollback()
        logger.info(f"【素材任务】任务执行结束 task={task_id}")


__all__ = ["run_material_sync_task"]
