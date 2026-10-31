"""按服务隔离 app 包运行回归；在对应本地容器执行，平台由各用例模拟。"""
import argparse
from pathlib import Path
import sys
import unittest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('service', choices=('backend', 'websocket', 'scheduler'))
    args = parser.parse_args()
    groups = {
        'websocket': ['test_refund_notification.py', 'test_upstream_account_startup.py'],
        'scheduler': ['test_scheduler_publish_runtime.py'],
    }
    directory = Path(__file__).resolve().parent
    excluded = {name for names in groups.values() for name in names}
    names = (sorted(path.name for path in directory.glob('test_*.py') if path.name not in excluded)
             if args.service == 'backend' else groups[args.service])
    service_path = {'backend': '/app/backend-web', 'websocket': '/app/websocket', 'scheduler': '/app/scheduler'}[args.service]
    sys.path[:0] = [service_path, '/app', str(directory)]
    from loguru import logger
    from common.core.config import get_settings
    logger.remove()
    get_settings().sql_echo = False
    suite = unittest.TestSuite(unittest.defaultTestLoader.discover(str(directory), pattern=name) for name in names)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return not result.wasSuccessful()


if __name__ == '__main__':
    raise SystemExit(main())
