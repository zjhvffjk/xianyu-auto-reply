"""批量发布由scheduler统一扫描；状态与队列持久化。"""
from app.core.config import get_settings
from common.services.publish_batch_runner import PublishBatchRunner

batch_publish_task_service = PublishBatchRunner(static_root=get_settings().static_dir)
