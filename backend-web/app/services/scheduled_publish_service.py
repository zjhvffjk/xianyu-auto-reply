"""批量定时发布任务服务（创建/列表/取消）。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from common.models.product_material import ProductMaterial
from common.models.scheduled_publish_task import (
    DEFAULT_PUBLISH_INTERVAL_SECONDS,
    MIN_PUBLISH_INTERVAL_SECONDS,
    ScheduledPublishTask,
)
from common.models.xy_account import XYAccount
from common.utils.time_utils import get_beijing_now_naive


class ScheduledPublishService:
    """批量定时发布任务管理。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_task(
        self,
        *,
        user_id: int,
        material_ids: list[int],
        account_ids: list[str],
        start_at: datetime,
        interval_seconds: int,
    ) -> dict[str, Any]:
        """创建定时发布任务。

        素材与账号都按当前用户归属校验；开始时间早于当前时间的按立即开始处理。
        """
        unique_material_ids = list(dict.fromkeys(int(m) for m in material_ids))
        unique_account_ids = list(dict.fromkeys(str(a) for a in account_ids))

        # 素材归属校验：只认本人未删除的素材
        mat_stmt = select(func.count()).select_from(ProductMaterial).where(
            ProductMaterial.id.in_(unique_material_ids),
            ProductMaterial.user_id == user_id,
            ProductMaterial.is_deleted.is_(False),
        )
        valid_materials = int((await self.session.execute(mat_stmt)).scalar() or 0)
        if valid_materials != len(unique_material_ids):
            return {
                "success": False,
                "message": "有素材不存在或不属于当前用户，已拒绝创建",
            }

        # 账号归属校验
        acc_stmt = select(func.count()).select_from(XYAccount).where(
            XYAccount.account_id.in_(unique_account_ids),
            XYAccount.owner_id == user_id,
        )
        valid_accounts = int((await self.session.execute(acc_stmt)).scalar() or 0)
        if valid_accounts != len(unique_account_ids):
            return {
                "success": False,
                "message": "有账号不存在或不属于当前用户，已拒绝创建",
            }

        now = get_beijing_now_naive()
        # 开始时间已过的任务立即开始（第一轮扫描就会发出第一条）
        effective_start = start_at if start_at > now else now
        total_count = len(unique_account_ids) * len(unique_material_ids)

        task = ScheduledPublishTask(
            user_id=user_id,
            material_ids=unique_material_ids,
            account_ids=unique_account_ids,
            start_at=effective_start,
            interval_seconds=interval_seconds,
            status="pending",
            next_index=0,
            next_run_at=effective_start,
            total_count=total_count,
        )
        self.session.add(task)
        await self.session.commit()
        await self.session.refresh(task)
        return {"success": True, "message": "定时发布任务已创建", "data": self._to_dict(task)}

    async def list_tasks(
        self, *, user_id: int, page: int = 1, page_size: int = 20
    ) -> dict[str, Any]:
        """分页查询当前用户的定时发布任务（新的在前）。"""
        page = max(page, 1)
        page_size = page_size if page_size in (10, 20, 50, 100) else 20

        count_stmt = (
            select(func.count())
            .select_from(ScheduledPublishTask)
            .where(ScheduledPublishTask.user_id == user_id)
        )
        total = int((await self.session.execute(count_stmt)).scalar() or 0)

        stmt = (
            select(ScheduledPublishTask)
            .where(ScheduledPublishTask.user_id == user_id)
            .order_by(ScheduledPublishTask.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": [self._to_dict(row) for row in rows],
        }

    async def cancel_task(self, *, user_id: int, task_id: int) -> dict[str, Any]:
        """取消任务（仅等待中/执行中可取消；已结束的任务原样返回）。"""
        task = await self.session.get(ScheduledPublishTask, task_id)
        if task is None or task.user_id != user_id:
            return {"success": False, "message": "任务不存在"}
        if task.status in ("completed", "cancelled", "failed"):
            return {
                "success": True,
                "message": f"任务已处于「{task.status}」状态，无需取消",
                "data": self._to_dict(task),
            }
        task.status = "cancelled"
        task.next_run_at = None
        await self.session.commit()
        await self.session.refresh(task)
        return {"success": True, "message": "任务已取消", "data": self._to_dict(task)}

    @staticmethod
    def _to_dict(task: ScheduledPublishTask) -> dict[str, Any]:
        """任务转字典（时间统一转 ISO 字符串，前端按本地时区展示）。"""
        return {
            "id": task.id,
            "material_ids": list(task.material_ids or []),
            "account_ids": list(task.account_ids or []),
            "start_at": task.start_at.isoformat() if task.start_at else None,
            "interval_seconds": task.interval_seconds,
            "status": task.status,
            "next_index": task.next_index,
            "next_run_at": task.next_run_at.isoformat() if task.next_run_at else None,
            "total_count": task.total_count,
            "success_count": task.success_count,
            "failed_count": task.failed_count,
            "last_error": task.last_error,
            "created_at": task.created_at.isoformat() if task.created_at else None,
        }


# 间隔下限（秒），路由校验用：技术下限（scheduler 扫描周期），非风控下限
MIN_INTERVAL_SECONDS = MIN_PUBLISH_INTERVAL_SECONDS
# 默认间隔（秒），路由默认值用：5 分钟，防平台风控的保守默认值
DEFAULT_INTERVAL_SECONDS = DEFAULT_PUBLISH_INTERVAL_SECONDS
