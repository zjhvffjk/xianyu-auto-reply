"""发布前内容风险检测（闲鱼违禁词 / 违规品类黑名单）。

背景
----
闲鱼对商品的审核不只看"敏感词"，还看**品类**。以 Hostinger 为例：这类境外虚拟主机的
文案里一个敏感词都没有，但整类被归入「非法服务、票证、违反公序良俗类 > 破网、翻墙软件
及 VPN 代理类商品或服务」（《闲鱼社区信息发布规范》第 7 类），发布后会被判违规、
删除商品并扣闲气值。

所以本模块做三道粗筛：
1. 违禁词 / 敏感词；
2. 违规品类与品牌黑名单（Hostinger、机场、clash、搬瓦工 等）；
3. 站外引流词与广告法极限词。

能力边界（务必知悉）
--------------------
- **只覆盖文字**（标题、描述、类目名等）。图片里的二维码、微信号需要 OCR，未在覆盖范围内。
- 命中不等于必然违规，未命中也不等于必然安全 —— 平台最终以自身模型 + 人工审核为准。
- 纯离线：词库随仓库分发，不联网、不外传商品内容。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

from loguru import logger

_TERMS_PATH = Path(__file__).resolve().parent.parent / "data" / "risk_terms.json"

_LEVEL_RANK = {"none": 0, "warn": 1, "block": 2}

# 用于抓 "v.p.n" / "v-p-n" / "v p n" 这类拆字绕过：先去掉所有非字母数字汉字再匹配一次
_NON_WORD_RE = re.compile(r"[^0-9a-z\u4e00-\u9fff]+")


def _to_halfwidth(text: str) -> str:
    """全角字符转半角（含全角空格），避免 "ＶＰＮ" 这类全角写法绕过。"""
    chars: list[str] = []
    for ch in text:
        code = ord(ch)
        if code == 0x3000:
            chars.append(" ")
        elif 0xFF01 <= code <= 0xFF5E:
            chars.append(chr(code - 0xFEE0))
        else:
            chars.append(ch)
    return "".join(chars)


class _TermIndex:
    """词表索引：term -> 所属分组，附带首字符集合与最长词长用于剪枝匹配。"""

    __slots__ = ("term_set", "meta", "max_len", "first_chars")

    def __init__(self, entries: list[tuple[str, dict[str, Any]]]) -> None:
        self.term_set: set[str] = set()
        self.meta: dict[str, dict[str, Any]] = {}
        for term, group in entries:
            normalized = str(term or "").strip().lower()
            if not normalized:
                continue
            self.term_set.add(normalized)
            existing = self.meta.get(normalized)
            # 同一个词出现在多个分组时，保留风险等级更高的那个
            if existing is None or (
                _LEVEL_RANK.get(group.get("level", "warn"), 1)
                > _LEVEL_RANK.get(existing.get("level", "warn"), 1)
            ):
                self.meta[normalized] = group
        self.max_len = max((len(t) for t in self.term_set), default=1)
        self.first_chars = {t[0] for t in self.term_set if t}

    def scan(self, haystack: str) -> set[str]:
        """返回 haystack 中命中的所有词（滑动窗口 + 首字符剪枝）。"""
        found: set[str] = set()
        if not haystack or not self.term_set:
            return found
        n = len(haystack)
        terms = self.term_set
        firsts = self.first_chars
        max_len = self.max_len
        for i in range(n):
            if haystack[i] not in firsts:
                continue
            limit = min(n, i + max_len)
            for j in range(i + 1, limit + 1):
                frag = haystack[i:j]
                if frag in terms:
                    found.add(frag)
        return found


_cache: dict[str, Any] = {"mtime": None, "index": None, "meta": None}


def _load_terms() -> tuple[_TermIndex, dict[str, Any]]:
    """加载词库（按文件 mtime 热更新，避免每次请求都读盘）。"""
    try:
        mtime = _TERMS_PATH.stat().st_mtime
    except OSError:
        logger.warning(f"违禁词库文件缺失，风险检测将空转: {_TERMS_PATH}")
        return _TermIndex([]), {}

    if _cache["mtime"] == mtime and _cache["index"] is not None:
        return _cache["index"], _cache["meta"]

    try:
        raw = json.loads(_TERMS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(f"违禁词库解析失败，沿用空词表: {exc!r}")
        return _TermIndex([]), {}

    entries: list[tuple[str, dict[str, Any]]] = []
    for group in raw.get("groups") or []:
        if not isinstance(group, dict):
            continue
        for term in group.get("terms") or []:
            entries.append((term, group))

    index = _TermIndex(entries)
    _cache["mtime"] = mtime
    _cache["index"] = index
    _cache["meta"] = raw
    logger.info(
        f"违禁词库已加载: {len(index.term_set)} 个词 / {len(raw.get('groups') or [])} 个分组"
    )
    return index, raw


def check_texts(texts: Iterable[str | None]) -> dict[str, Any]:
    """检测一组文本，返回命中详情与总体风险等级。

    Returns:
        {
          "level": "block" | "warn" | "none",
          "blocked": bool,          # level == block
          "hit_count": int,
          "hits": [{"term", "level", "group_id", "label"}],
          "rules": [{"group_id", "label", "level", "rule", "hint"}],
          "term_count": int,        # 当前词库规模，便于排查
        }
    """
    index, _raw = _load_terms()
    hits: dict[str, dict[str, Any]] = {}

    for item in texts:
        if not item:
            continue
        normalized = _to_halfwidth(str(item)).lower()
        # 两个变体都扫：去空白版 + 去掉全部符号的紧凑版
        for variant in (re.sub(r"\s+", "", normalized), _NON_WORD_RE.sub("", normalized)):
            if not variant:
                continue
            for term in index.scan(variant):
                hits.setdefault(term, index.meta.get(term) or {})

    if not hits:
        return {
            "level": "none", "blocked": False, "hit_count": 0,
            "hits": [], "rules": [], "term_count": len(index.term_set),
        }

    top = "none"
    detail: list[dict[str, Any]] = []
    rules: dict[str, dict[str, Any]] = {}
    for term in sorted(hits):
        group = hits[term]
        level = group.get("level", "warn")
        if _LEVEL_RANK.get(level, 1) > _LEVEL_RANK.get(top, 0):
            top = level
        detail.append({
            "term": term,
            "level": level,
            "group_id": group.get("id", ""),
            "label": group.get("label", ""),
        })
        gid = group.get("id", "")
        if gid and gid not in rules:
            rules[gid] = {
                "group_id": gid,
                "label": group.get("label", ""),
                "level": level,
                "rule": group.get("rule", ""),
                "hint": group.get("hint", ""),
            }

    return {
        "level": top,
        "blocked": top == "block",
        "hit_count": len(detail),
        "hits": detail,
        "rules": list(rules.values()),
        "term_count": len(index.term_set),
    }


class ContentRiskChecker:
    """对外入口，沿项目既有 service 的类风格提供静态调用。"""

    @staticmethod
    def check(
        title: str | None = None,
        description: str | None = None,
        extra: Iterable[str | None] | None = None,
    ) -> dict[str, Any]:
        texts: list[str | None] = [title, description]
        if extra:
            texts.extend(extra)
        return check_texts(texts)
