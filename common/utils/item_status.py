"""统一解析平台商品状态；未知状态不推断为在售。"""
from typing import Any

PLATFORM_STATUS_CODE_MAP = {
    '0': '在卖', '1': '售出', '-1': '用户删除', '-2': '下架', '-12': '下架', '-4': '违规',
}


def resolve_platform_status(code: Any, description: Any = None) -> str:
    description = str(description or '').strip()
    if description:
        return description
    if isinstance(code, bool):
        return ''
    # 仅识别完整整数状态码，避免把小数或其他未知值误归为在售。
    return PLATFORM_STATUS_CODE_MAP.get(str(code).strip(), '')
