"""在调度容器运行，验证真实发布依赖可加载；不发起平台请求。"""
import sys
import unittest

sys.path.insert(0, '/app/scheduler')
import app.services.scheduler_service  # 保持调度服务实际的 app 包搜索路径
from common.services.xianyu_publish_service import (
    get_publish_account_capability_service_class,
    get_xianyu_direct_publisher_class,
    get_xianyu_personal_publisher_class,
)


class SchedulerPublishRuntimeTests(unittest.TestCase):
    def test_account_capability_dependency_available(self):
        self.assertTrue(callable(get_publish_account_capability_service_class()))

    def test_fish_shop_publisher_dependency_available(self):
        self.assertTrue(callable(get_xianyu_direct_publisher_class()))

    def test_personal_publisher_dependency_available(self):
        self.assertTrue(callable(get_xianyu_personal_publisher_class()))


if __name__ == '__main__':
    unittest.main()
