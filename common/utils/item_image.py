"""从现有商品快照取主图，不增加平台请求。"""
from typing import Any


def resolve_item_image(detail: dict[str, Any]) -> str:
    pic = detail.get('pic_info')
    pic = pic if isinstance(pic, dict) else {}
    candidates = [detail.get('image_url'), pic.get('picUrl'), pic.get('url')]
    images = [entry for entry in detail.get('imageInfoDOList') or []
              if isinstance(entry, dict) and str(entry.get('type', 0)) == '0']
    images.sort(key=lambda entry: str(entry.get('major')).lower() != 'true')
    candidates.extend(entry.get('url') for entry in images)
    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        url = candidate.strip()
        if url.startswith('//'):
            url = 'https:' + url
        if url.startswith(('https://', 'http://')):
            return url
    return ''
