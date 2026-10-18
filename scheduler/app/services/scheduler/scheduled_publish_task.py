"""Scheduler 中的批量定时发布 runner。"""
from __future__ import annotations

from common.services.scheduled_publish_task import scheduled_publish_task_service


class SchedulerScheduledPublishTask:
    """封装公共定时发布服务，避免 scheduler 复制业务逻辑。"""

    async def execute(self) -> None:
        """执行一次定时发布扫描（每轮只发到期任务的下一条）。"""
        await scheduled_publish_task_service.execute()


scheduled_publish_runner = SchedulerScheduledPublishTask()
