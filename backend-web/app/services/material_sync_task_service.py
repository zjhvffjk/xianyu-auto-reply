"""
素材库批量任务服务（从商品同步 / 刷新价格库存）

功能：
1. 任务的创建（带并发闸门：同一用户同一类型只允许一个进行中）、查询
2. 执行器逐批回写进度（processed/created/revived/updated/failed/skipped/remaining）
3. 取消（软取消）、僵死任务清理（服务重启后 running 无进度更新的）
4. 进度全部落库：页面刷新、关标签页、服务重启后都能从断点继续查
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, Optional

from loguru import logger
from sqlalchemy import desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from common.db.session import async_session_maker
from common.models.material_sync_task import (
    STALE_RUNNING_MINUTES,
    TASK_ACTIVE_STATUSES,
    TASK_STATUS_CANCELED,
    TASK_STATUS_FAILED,
    TASK_STATUS_PENDING,
    TASK_STATUS_PARTIAL,
    TASK_STATUS_RUNNING,
    TASK_STATUS_SUCCESS,
    TASK_TYPES,
    MaterialSyncTask,
    task_to_dict,
    truncate_error_message,
)
from common.models.user import User
from common.utils.time_utils import get_beijing_now_naive


class MaterialSyncTaskService:
    """素材库批量任务的数据库操作"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ---------- 创建与闸门 ----------

    async def get_active_task(
        self, owner_id: int, task_type: str
    ) -> Optional[MaterialSyncTask]:
        """查询该用户该类型下仍在进行中的任务（含僵死清理后的结果）。

        先清理僵死任务再查询，避免服务重启后残留的 running 把新任务永久挡住。
        """
        await self.fail_stale_running(owner_id=owner_id, task_type=task_type)
        result = await self.session.execute(
            select(MaterialSyncTask)
            .where(
                MaterialSyncTask.owner_id == owner_id,
                MaterialSyncTask.task_type == task_type,
                MaterialSyncTask.is_deleted.is_(False),
                MaterialSyncTask.status.in_(TASK_ACTIVE_STATUSES),
            )
            .order_by(desc(MaterialSyncTask.id))
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def create_task(
        self,
        *,
        owner_id: int,
        task_id: str,
        task_type: str,
        account_pk: Optional[int],
        owner_scope: Optional[int],
        total_missing: int,
    ) -> Optional[MaterialSyncTask]:
        """创建任务（pending 状态，等后台执行器领取）。

        先锁定用户行再查进行中任务，避免「先查数量、再创建」的竞态
        （用户行是稳定且唯一的锁目标，可跨多个 Web 进程生效）。
        """
        user_exists = await self.session.scalar(
            select(User.id).where(User.id == owner_id).with_for_update()
        )
        if user_exists is None:
            raise ValueError("任务所属用户不存在")

        active = await self.get_active_task(owner_id, task_type)
        if active is not None:
            return None

        task = MaterialSyncTask(
            owner_id=owner_id,
            task_id=task_id,
            task_type=task_type,
            account_pk=account_pk,
            owner_scope=owner_scope,
            total_missing=total_missing,
            remaining=total_missing,
        )
        self.session.add(task)
        await self.session.commit()
        await self.session.refresh(task)
        return task

    # ---------- 查询 ----------

    async def get_task(
        self, task_id: str, owner_id: Optional[int] = None
    ) -> Optional[MaterialSyncTask]:
        """按任务ID查询任务

        Args:
            task_id: 任务ID。
            owner_id: 归属用户ID；为 None 时不做用户过滤（后台任务自身调用）。
        """
        conditions = [
            MaterialSyncTask.task_id == task_id,
            MaterialSyncTask.is_deleted.is_(False),
        ]
        if owner_id is not None:
            conditions.append(MaterialSyncTask.owner_id == owner_id)
        result = await self.session.execute(
            select(MaterialSyncTask).where(*conditions)
        )
        return result.scalar_one_or_none()

    async def get_latest_task(
        self, owner_id: int, task_type: str
    ) -> Optional[MaterialSyncTask]:
        """查询该用户该类型最近的一次任务（已结束的也返回，供前端展示上次结果）。"""
        result = await self.session.execute(
            select(MaterialSyncTask)
            .where(
                MaterialSyncTask.owner_id == owner_id,
                MaterialSyncTask.task_type == task_type,
                MaterialSyncTask.is_deleted.is_(False),
            )
            .order_by(desc(MaterialSyncTask.id))
            .limit(1)
        )
        return result.scalar_one_or_none()

    # ---------- 进度推进 ----------

    async def mark_task_running(self, task_id: str) -> bool:
        """把等待中的任务标记为执行中并记录开始时间。

        仅允许 pending → running，避免用户在后台执行器真正启动前点击取消后，
        执行器又把已取消任务覆盖回 running。

        Returns:
            是否成功完成状态转换。
        """
        result = await self.session.execute(
            update(MaterialSyncTask)
            .where(
                MaterialSyncTask.task_id == task_id,
                MaterialSyncTask.status == TASK_STATUS_PENDING,
                MaterialSyncTask.is_deleted.is_(False),
            )
            .values(status=TASK_STATUS_RUNNING, started_at=get_beijing_now_naive())
        )
        await self.session.commit()
        return bool(result.rowcount)

    async def update_progress(self, task_id: str, batch: Dict[str, Any]) -> None:
        """按一批处理结果累加进度（执行器每批调用一次）。

        Args:
            task_id: 任务ID。
            batch: 本批统计，键含 created/revived/updated/failed/skipped/
                processed/remaining，缺省按 0。
        """
        await self.session.execute(
            update(MaterialSyncTask)
            .where(MaterialSyncTask.task_id == task_id)
            .values(
                processed=MaterialSyncTask.processed + int(batch.get("processed") or 0),
                created=MaterialSyncTask.created + int(batch.get("created") or 0),
                revived=MaterialSyncTask.revived + int(batch.get("revived") or 0),
                updated=MaterialSyncTask.updated + int(batch.get("updated") or 0),
                failed=MaterialSyncTask.failed + int(batch.get("failed") or 0),
                skipped=MaterialSyncTask.skipped + int(batch.get("skipped") or 0),
                remaining=int(batch.get("remaining") or 0),
            )
        )
        await self.session.commit()

    async def finish_task(
        self, task_id: str, error_message: Optional[str] = None
    ) -> None:
        """结束任务：按成功/失败条数决定最终状态。

        已取消的任务保持 canceled，不被覆盖。

        注意：必须用标量查询读计数，不能用 ORM 实例——进度是 UPDATE 累加的，
        identity map 里的旧实例不会刷新，读它会拿到创建时的 0。
        """
        row = (
            await self.session.execute(
                select(
                    MaterialSyncTask.status,
                    MaterialSyncTask.created,
                    MaterialSyncTask.revived,
                    MaterialSyncTask.updated,
                    MaterialSyncTask.failed,
                ).where(MaterialSyncTask.task_id == task_id)
            )
        ).one_or_none()
        if row is None:
            return

        current_status, created, revived, updated, failed = row
        if current_status == TASK_STATUS_CANCELED:
            await self.session.execute(
                update(MaterialSyncTask)
                .where(MaterialSyncTask.task_id == task_id)
                .values(finished_at=get_beijing_now_naive())
            )
            await self.session.commit()
            return

        success = (created or 0) + (revived or 0) + (updated or 0)
        if success and (failed or 0):
            status = TASK_STATUS_PARTIAL
        elif success:
            status = TASK_STATUS_SUCCESS
        else:
            status = TASK_STATUS_FAILED

        values: dict = {"status": status, "finished_at": get_beijing_now_naive()}
        if error_message:
            values["error_message"] = truncate_error_message(error_message)

        await self.session.execute(
            update(MaterialSyncTask)
            .where(MaterialSyncTask.task_id == task_id)
            .values(**values)
        )
        await self.session.commit()

    # ---------- 取消与僵死清理 ----------

    async def cancel_task(self, task_id: str, owner_id: int) -> bool:
        """取消任务（软取消：只改状态，执行器在下一批开始前自行停止）。

        Returns:
            是否成功取消；任务不存在或已结束时返回 False。
        """
        status = await self.session.scalar(
            select(MaterialSyncTask.status).where(
                MaterialSyncTask.task_id == task_id,
                MaterialSyncTask.owner_id == owner_id,
                MaterialSyncTask.is_deleted.is_(False),
            )
        )
        if status is None or status not in TASK_ACTIVE_STATUSES:
            return False
        await self.session.execute(
            update(MaterialSyncTask)
            .where(MaterialSyncTask.task_id == task_id)
            .values(status=TASK_STATUS_CANCELED, error_message="用户已取消任务")
        )
        await self.session.commit()
        return True

    async def is_canceled(self, task_id: str) -> bool:
        """查询任务是否已被取消（执行器每批开始前调用）。"""
        status = await self.session.scalar(
            select(MaterialSyncTask.status).where(
                MaterialSyncTask.task_id == task_id
            )
        )
        return status == TASK_STATUS_CANCELED

    async def fail_stale_running(
        self, owner_id: int, task_type: str
    ) -> int:
        """把长时间没有进度更新的 running 任务标记为失败。

        服务重启/停机时，后台执行器不会自己收尾，任务状态会永远停在
        pending/running，把新任务永久挡在闸门外。执行器每批都会更新
        updated_at（ON UPDATE CURRENT_TIMESTAMP），因此「running 且
        updated_at 早于 STALE_RUNNING_MINUTES 分钟前」即视为僵死。

        Returns:
            被标记为失败的任务条数。
        """
        threshold = get_beijing_now_naive() - timedelta(minutes=STALE_RUNNING_MINUTES)
        result = await self.session.execute(
            update(MaterialSyncTask)
            .where(
                MaterialSyncTask.owner_id == owner_id,
                MaterialSyncTask.task_type == task_type,
                MaterialSyncTask.is_deleted.is_(False),
                MaterialSyncTask.status == TASK_STATUS_RUNNING,
                MaterialSyncTask.updated_at.is_not(None),
                MaterialSyncTask.updated_at < threshold,
            )
            .values(
                status=TASK_STATUS_FAILED,
                error_message="任务长时间无进度，已按中断处理（多为服务重启）",
                finished_at=get_beijing_now_naive(),
            )
        )
        await self.session.commit()
        affected = int(result.rowcount or 0)
        if affected:
            logger.info(
                f"【素材任务】清理僵死任务 user={owner_id} type={task_type} 数量={affected}"
            )
        return affected


def task_progress_to_dict(task: MaterialSyncTask) -> Dict[str, Any]:
    """任务行 → 接口字典（复用模型的 task_to_dict，便于测试与路由统一引用）。"""
    return task_to_dict(task)


async def fail_all_stale_running() -> int:
    """把服务重启前遗留的未结束素材任务标记为失败（启动自检，幂等）。

    进程被重启/停机时，后台执行器不会自己收尾，任务状态会永远停在
    pending/running，把新任务永久挡在闸门外。启动时清理一次。
    """
    try:
        threshold = get_beijing_now_naive() - timedelta(minutes=STALE_RUNNING_MINUTES)
        async with async_session_maker() as session:
            result = await session.execute(
                update(MaterialSyncTask)
                .where(
                    MaterialSyncTask.is_deleted.is_(False),
                    MaterialSyncTask.status.in_(TASK_ACTIVE_STATUSES),
                    # pending 说明执行器从未启动（重启丢的），一律按中断处理；
                    # running 需确认长时间无进度更新，避免误杀刚创建的任务
                    (MaterialSyncTask.status == TASK_STATUS_PENDING)
                    | (
                        (MaterialSyncTask.status == TASK_STATUS_RUNNING)
                        & MaterialSyncTask.updated_at.is_not(None)
                        & (MaterialSyncTask.updated_at < threshold)
                    ),
                )
                .values(
                    status=TASK_STATUS_FAILED,
                    error_message="服务重启，任务已中断",
                    finished_at=get_beijing_now_naive(),
                )
            )
            await session.commit()
            affected = int(result.rowcount or 0)
            if affected:
                logger.info(f"【素材任务】启动自检：已把 {affected} 个中断任务标记为失败")
            return affected
    except Exception as exc:  # noqa: BLE001 - 清理失败不能影响服务启动
        logger.warning(f"【素材任务】启动自检清理遗留任务失败：{exc}")
        return 0


__all__ = [
    "MaterialSyncTaskService",
    "fail_all_stale_running",
    "task_progress_to_dict",
    "TASK_TYPES",
]
