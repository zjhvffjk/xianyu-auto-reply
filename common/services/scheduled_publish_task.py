"""批量定时发布任务执行器。

scheduler 每 30 秒调一次 execute()：查出「下一条执行时间已到」的任务，
每个任务只发队列中的一条（账号 × 素材 展开，账号外层，与立即发布语义一致），
发完把 next_index 推进、next_run_at 加上间隔，全部发完置 completed。
单条发布用独立 session，发布内部的回滚不会波及任务状态更新。
"""
from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from datetime import datetime, timedelta
from typing import Any

from loguru import logger
from sqlalchemy import select

from common.core.config import get_settings
from common.db.redis_client import distributed_lock
from common.db.session import async_session_maker
from common.models.product_material import ProductMaterial
from common.models.scheduled_publish_task import ScheduledPublishTask
from common.services.auto_relist_utils import material_to_publish_data
from common.services.publish_execution_service import execute_single_publish
from common.utils.time_utils import get_beijing_now_naive

# 每轮最多处理的任务数：单条发布约 2~4 秒，10 个任务约 40 秒，留足锁租约余量
MAX_TASKS_PER_SCAN = 10
# runner 锁租约（秒）：需覆盖一轮扫描的最坏耗时
RUNNER_LOCK_EXPIRE_SECONDS = 180


def build_publish_queue(
    material_ids: list[int], account_ids: list[str]
) -> list[tuple[str, int]]:
    """把素材与账号展开成发布队列（账号外层，与立即发布语义一致）。"""
    return [(acc, mat) for acc in account_ids for mat in material_ids]


def advance_after_publish(
    *,
    next_index: int,
    queue_len: int,
    success: bool,
    interval_seconds: int,
    now: datetime,
) -> dict[str, Any]:
    """发布一条后的任务状态推进（纯函数，便于单测）。

    Args:
        next_index: 刚发布完的那条的下标（从 0 起）。
        queue_len: 队列总长度。
        success: 该条是否发布成功（失败也推进，不阻塞后续）。
        interval_seconds: 每条间隔秒数。
        now: 当前时间（北京时间 naive）。

    Returns:
        dict: 新的 next_index / status / next_run_at。
    """
    advanced = next_index + 1
    if advanced >= queue_len:
        return {"next_index": advanced, "status": "completed", "next_run_at": None}
    return {
        "next_index": advanced,
        "status": "running",
        "next_run_at": now + timedelta(seconds=max(1, interval_seconds)),
    }


class ScheduledPublishTaskService:
    """定时发布扫描执行器（scheduler 容器内运行）。"""

    def __init__(self) -> None:
        settings = get_settings()
        self._static_dir = settings.static_dir
        self._local_lock = asyncio.Lock()

    async def execute(self) -> None:
        """执行一次扫描，单个任务异常不会终止后续任务。"""
        if self._local_lock.locked():
            logger.warning("[定时发布] 本地锁被占用（上一轮仍在执行），本次跳过")
            return
        async with self._local_lock:
            async with AsyncExitStack() as stack:
                try:
                    runner_lock = await stack.enter_async_context(
                        distributed_lock(
                            "scheduled_publish:runner",
                            expire=RUNNER_LOCK_EXPIRE_SECONDS,
                            blocking=False,
                        )
                    )
                except Exception as exc:  # noqa: BLE001 - Redis 不可用时跳过本轮
                    logger.warning("[定时发布] Redis 调度锁不可用，本次跳过: {}", exc)
                    return
                if not runner_lock.is_locked:
                    logger.info("[定时发布] 调度锁被其他 worker 持有，本次跳过")
                    return
                await self._scan_due_tasks()

    async def _scan_due_tasks(self) -> None:
        """查出到点的任务并逐条发布。"""
        now = get_beijing_now_naive()
        async with async_session_maker() as session:
            stmt = (
                select(ScheduledPublishTask.id)
                .where(ScheduledPublishTask.status.in_(("pending", "running")))
                .where(ScheduledPublishTask.next_run_at.is_not(None))
                .where(ScheduledPublishTask.next_run_at <= now)
                .order_by(ScheduledPublishTask.next_run_at)
                .limit(MAX_TASKS_PER_SCAN)
            )
            task_ids = list((await session.execute(stmt)).scalars().all())

        if not task_ids:
            return
        logger.info("[定时发布] 本轮到期任务: {}", task_ids)
        for task_id in task_ids:
            try:
                await self._publish_one(task_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - 单任务异常不中断整轮
                logger.opt(exception=exc).error("[定时发布] 任务执行异常 task_id={}", task_id)

    async def _publish_one(self, task_id: int) -> None:
        """发布一个任务的队列中的下一条。"""
        now = get_beijing_now_naive()
        async with async_session_maker() as session:
            task = await session.get(ScheduledPublishTask, task_id)
            if task is None or task.status not in ("pending", "running"):
                return

            material_ids = [int(m) for m in (task.material_ids or [])]
            account_ids = [str(a) for a in (task.account_ids or [])]
            # 队列 = 账号 × 素材（账号外层），与立即发布的执行顺序一致
            queue = build_publish_queue(material_ids, account_ids)
            if not queue:
                task.status = "failed"
                task.last_error = "任务队列为空（素材或账号列表为空）"
                task.next_run_at = None
                await session.commit()
                return

            if task.next_index >= len(queue):
                task.status = "completed"
                task.next_run_at = None
                await session.commit()
                return

            account_id, material_id = queue[task.next_index]
            material = await session.get(ProductMaterial, material_id)
            if material is None or material.is_deleted:
                # 素材不存在或已删除：记失败跳过，不阻塞后续队列
                task.failed_count += 1
                task.last_error = f"素材 {material_id} 不存在或已删除，已跳过"
                logger.warning("[定时发布] task_id={} {}", task_id, task.last_error)
            else:
                item_data = material_to_publish_data(material)
                result = await execute_single_publish(
                    session=session,
                    user_id=task.user_id,
                    account_id=account_id,
                    item_data=item_data,
                    static_root=self._static_dir,
                )
                if result.get("success"):
                    task.success_count += 1
                    logger.info(
                        "[定时发布] task_id={} 第 {}/{} 条发布成功: account={} material={}",
                        task_id, task.next_index + 1, len(queue), account_id, material_id,
                    )
                else:
                    task.failed_count += 1
                    task.last_error = str(result.get("message") or "发布失败")[:500]
                    logger.warning(
                        "[定时发布] task_id={} 第 {}/{} 条发布失败: account={} material={} msg={}",
                        task_id, task.next_index + 1, len(queue), account_id, material_id,
                        task.last_error,
                    )

            advanced = advance_after_publish(
                next_index=task.next_index,
                queue_len=len(queue),
                success=True,
                interval_seconds=task.interval_seconds,
                now=now,
            )
            task.next_index = advanced["next_index"]
            task.status = advanced["status"]
            task.next_run_at = advanced["next_run_at"]
            if advanced["status"] == "completed":
                logger.info(
                    "[定时发布] task_id={} 全部完成: 成功 {} 失败 {}",
                    task_id, task.success_count, task.failed_count,
                )
            await session.commit()


scheduled_publish_task_service = ScheduledPublishTaskService()
