"""
商品库 → 素材库 同步服务

功能：
1. 计算「商品库里有、素材库里没有」的差集（按源闲鱼 item_id 精确判重，幂等）
2. 分批把缺失商品补进素材库：标题/价格取商品同步快照，
   描述/图片/平台分类/成色优先取鱼小铺详情接口（mtop.idle.pc.backend.idleitem.editdetail），
   接口不可用时退回快照数据，保证每条素材都可用
3. 全程只读闲鱼、只写当前用户的素材表；命中风控关键词立即停止，剩余留待下次继续

判重键：
- 素材表 source_item_id 存放源闲鱼 item_id；手动新建的素材该列为空。
- 历史素材只有 remark（"源闲鱼 item_id=x acc=y"），同步前会自动回填到 source_item_id，
  避免历史素材被重复建一遍。
- 软删除的素材同样算「已存在」，不会被自动重建（用户删掉的商品不复活）。
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Iterable

from loguru import logger
from sqlalchemy import func, select, text as sqltext
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.xianyu_item_edit_service import fetch_seller_item_edit_detail
from common.models.product_material import ProductMaterial
from common.models.xy_account import XYAccount
from common.models.xy_catalog_item import XYCatalogItem
from common.services.account_cooldown import AccountCooldownManager

# 逐条调用平台接口的间隔（秒），避免短时间密集请求触发平台风控
THROTTLE_SECONDS = 2.5
# 单次请求默认/最多处理的商品数（前端可循环调用直到 remaining 归零）
DEFAULT_BATCH_LIMIT = 8
MAX_BATCH_LIMIT = 20

MAX_IMAGES = 9
MAX_TITLE = 200
MAX_DESC = 5000
# 失败明细最多回传条数，避免响应体过大
MAX_REPORTED_ERRORS = 20

_REMARK_PREFIX = "源闲鱼 item_id="
# remark → source_item_id 的提取表达式（"源闲鱼 item_id=123 acc=4" → 123）
_REMARK_SUBSTRING_SQL = "SUBSTRING_INDEX(SUBSTRING_INDEX(remark,'item_id=',-1),' acc=',1)"


def _snapshot_detail(metadata: Any) -> dict[str, Any]:
    """解析商品同步快照 metadata，取出内层 detail。

    说明：`metadata.detail` 是内嵌 JSON 字符串（列表接口原始返回），需要再解析一层。
    """
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except (ValueError, TypeError):
            metadata = {}
    detail = (metadata or {}).get("detail") or {}
    if isinstance(detail, str):
        try:
            detail = json.loads(detail)
        except (ValueError, TypeError):
            detail = {}
    return detail if isinstance(detail, dict) else {}


def build_images_from_snapshot(detail: dict[str, Any]) -> list[str]:
    """从商品快照里提取图片 URL 列表（主图优先，去重，最多 9 张）。"""
    urls: list[str] = []
    pic = detail.get("pic_info") or {}
    main = str(pic.get("picUrl") or "").strip()
    if main:
        urls.append(main)

    params = detail.get("detail_params") or {}
    raw = params.get("imageInfos")
    infos: list[Any] = []
    if isinstance(raw, str) and raw.strip():
        try:
            infos = json.loads(raw)
        except (ValueError, TypeError):
            infos = []
    elif isinstance(raw, list):
        infos = raw
    for item in sorted(
        (it for it in infos if isinstance(it, dict)),
        key=lambda x: 0 if x.get("major") else 1,
    ):
        url = str(item.get("url") or "").strip()
        if url:
            urls.append(url)

    single = str(params.get("picUrl") or "").strip()
    if single:
        urls.append(single)

    seen: set[str] = set()
    ordered: list[str] = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            ordered.append(url)
    return ordered[:MAX_IMAGES]


def parse_price(raw: Any) -> float:
    """把快照里的价格文本转成元（快照价格是字符串，可能带 ￥ 与千分位）。"""
    text = str(raw or "").strip()
    for ch in ("\u00a5", "\uffe5", ",", " "):
        text = text.replace(ch, "")
    try:
        price = round(float(text), 2)
    except (TypeError, ValueError):
        return 0.01
    return price if price > 0 else 0.01


class MaterialSyncService:
    """把商品库里的在售商品补进商品素材库（只补缺口，不修改已有素材）。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ---------- 判重键维护 ----------

    async def backfill_source_item_id(self, user_id: int) -> int:
        """把历史素材 remark 里的源商品ID回填到 source_item_id（幂等）。

        Returns:
            int: 本次回填的行数（已回填过的不会重复计入）。
        """
        result = await self.session.execute(
            sqltext(
                "UPDATE xy_product_materials "
                f"SET source_item_id = {_REMARK_SUBSTRING_SQL} "
                "WHERE user_id = :u AND source_item_id IS NULL "
                f"AND remark LIKE :prefix AND {_REMARK_SUBSTRING_SQL} REGEXP '^[0-9]+$'"
            ),
            {"u": user_id, "prefix": f"{_REMARK_PREFIX}%"},
        )
        await self.session.commit()
        return int(result.rowcount or 0)

    # ---------- 差集 ----------

    def _pooled_source_ids(self, user_id: int):
        """当前用户素材池里已存在的源商品ID子查询（含软删除，避免删掉的被重建）。"""
        return (
            select(ProductMaterial.source_item_id)
            .where(ProductMaterial.user_id == user_id)
            .where(ProductMaterial.source_item_id.is_not(None))
        )

    def _missing_stmt(self, *, user_id: int, owner_scope: int | None):
        stmt = (
            select(XYCatalogItem)
            .where(XYCatalogItem.item_id.is_not(None))
            .where(XYCatalogItem.item_id != "")
            .where(XYCatalogItem.item_id.not_in(self._pooled_source_ids(user_id)))
            .order_by(XYCatalogItem.account_pk, XYCatalogItem.item_id)
        )
        # 管理员（owner_scope=None）可见全部账号商品；普通用户仅本人账号
        if owner_scope is not None:
            stmt = stmt.where(XYCatalogItem.owner_id == owner_scope)
        return stmt

    async def count_missing(self, *, user_id: int, owner_scope: int | None) -> int:
        """统计还差多少条商品没进素材池。"""
        stmt = (
            select(func.count())
            .select_from(XYCatalogItem)
            .where(XYCatalogItem.item_id.is_not(None))
            .where(XYCatalogItem.item_id != "")
            .where(XYCatalogItem.item_id.not_in(self._pooled_source_ids(user_id)))
        )
        if owner_scope is not None:
            stmt = stmt.where(XYCatalogItem.owner_id == owner_scope)
        return int((await self.session.execute(stmt)).scalar() or 0)

    async def preview(self, *, user_id: int, owner_scope: int | None) -> dict[str, Any]:
        """同步前预览：回填判重键 + 统计缺口。"""
        backfilled = await self.backfill_source_item_id(user_id)
        rows = (await self.session.execute(
            self._missing_stmt(user_id=user_id, owner_scope=owner_scope)
        )).scalars().all()

        by_account: dict[str, int] = {}
        for row in rows:
            key = str(row.account_pk)
            by_account[key] = by_account.get(key, 0) + 1

        return {
            "missing": len(rows),
            "by_account": by_account,
            "pooled": int((await self.session.execute(
                select(func.count())
                .select_from(ProductMaterial)
                .where(ProductMaterial.user_id == user_id)
            )).scalar() or 0),
            "backfilled": backfilled,
        }

    # ---------- 批量写入 ----------

    async def _load_accounts(self, account_pks: Iterable[int]) -> dict[int, XYAccount]:
        pks = [int(pk) for pk in account_pks]
        if not pks:
            return {}
        rows = (await self.session.execute(
            select(XYAccount).where(XYAccount.id.in_(pks))
        )).scalars().all()
        return {acc.id: acc for acc in rows}

    async def sync_batch(
        self,
        *,
        user_id: int,
        owner_scope: int | None,
        limit: int = DEFAULT_BATCH_LIMIT,
    ) -> dict[str, Any]:
        """同步一批缺失商品进素材池。

        Args:
            user_id: 素材归属用户（写入 xy_product_materials.user_id）。
            owner_scope: 商品归属过滤；None 表示不限制（管理员）。
            limit: 本次最多处理条数。

        Returns:
            dict: 进度与结果统计，含 remaining（还剩多少条）供前端继续调用。
        """
        batch_limit = max(1, min(int(limit or DEFAULT_BATCH_LIMIT), MAX_BATCH_LIMIT))
        await self.backfill_source_item_id(user_id)

        total_missing = await self.count_missing(user_id=user_id, owner_scope=owner_scope)
        if total_missing <= 0:
            return {
                "total_missing": 0, "processed": 0, "created": 0, "failed": 0,
                "skipped": 0, "remaining": 0, "aborted": False, "errors": [],
            }

        rows = (await self.session.execute(
            self._missing_stmt(user_id=user_id, owner_scope=owner_scope).limit(batch_limit)
        )).scalars().all()
        accounts = await self._load_accounts(row.account_pk for row in rows)

        created = 0
        failed = 0
        skipped = 0
        processed = 0
        aborted = False
        errors: list[dict[str, str]] = []

        for row in rows:
            item_id = str(row.item_id)
            title = str(row.title or "").strip()[:MAX_TITLE]
            if not title:
                skipped += 1
                processed += 1
                errors.append({"item_id": item_id, "reason": "商品标题为空，已跳过"})
                continue

            detail = _snapshot_detail(row.metadata_json)
            images = build_images_from_snapshot(detail)
            description = ""
            category_id = str(detail.get("category_id") or "").strip() or None
            category_name: str | None = None
            condition = "全新"

            account = accounts.get(int(row.account_pk))
            if account is not None and (account.cookie or "").strip():
                try:
                    result = await fetch_seller_item_edit_detail(
                        account_id=account.account_id,
                        cookie=account.cookie,
                        item_id=item_id,
                        owner_id=account.owner_id,
                    )
                except Exception as exc:  # noqa: BLE001 - 单条异常不应中断整批
                    logger.warning(f"【素材同步】item={item_id} 调用详情接口异常: {exc!r}")
                    result = {"success": False, "message": f"调用详情接口异常：{exc}"}

                # 平台可能刷新 Cookie，回写以免下次仍用旧值
                new_cookie = str(result.get("cookies_str") or "").strip()
                if new_cookie and new_cookie != (account.cookie or "").strip():
                    account.cookie = new_cookie

                if result.get("success"):
                    form = ((result.get("data") or {}).get("form") or {})
                    description = str(form.get("description") or "").strip()
                    category_id = str(form.get("platform_category_id") or "").strip() or category_id
                    category_name = str(form.get("platform_category_name") or "").strip() or None
                    condition = str(form.get("condition") or "").strip() or "全新"
                    real_images = [
                        url for url in (form.get("images") or [])
                        if isinstance(url, str) and url.startswith("http")
                    ]
                    if real_images:
                        images = real_images[:MAX_IMAGES]
                else:
                    message = str(result.get("message") or "获取商品详情失败")
                    # 命中风控则立即停止整批，剩余留给下次，避免继续扩大风险
                    if AccountCooldownManager.is_risk_control_error(message):
                        logger.warning(f"【素材同步】user={user_id} 命中风控信号，已停止：{message}")
                        aborted = True
                        errors.append({"item_id": item_id, "reason": message})
                        break
                    # 非风控失败：退回快照数据继续，仅记录原因
                    errors.append({"item_id": item_id, "reason": message})

            if not images:
                skipped += 1
                processed += 1
                if not any(err["item_id"] == item_id for err in errors):
                    errors.append({"item_id": item_id, "reason": "没有可用图片，已跳过"})
                continue

            material = ProductMaterial(
                user_id=user_id,
                title=title,
                description=(description or title)[:MAX_DESC],
                price=parse_price(row.price),
                category=category_name,
                platform_category_id=category_id,
                platform_category_name=category_name,
                platform_category_path=[],
                platform_attributes=[],
                category_source="manual",
                images=images,
                videos=[],
                specifications=[],
                sku_rows=[],
                quantity=1,
                delivery_method="express",
                shipping_method="free",
                support_pickup=False,
                postage=0,
                condition=condition,
                remark=f"{_REMARK_PREFIX}{item_id} acc={row.account_pk}",
                source_item_id=item_id,
            )
            self.session.add(material)
            try:
                await self.session.commit()
            except Exception as exc:  # noqa: BLE001 - 单条写入失败不影响整批
                await self.session.rollback()
                failed += 1
                processed += 1
                logger.warning(f"【素材同步】item={item_id} 写入失败: {exc!r}")
                errors.append({"item_id": item_id, "reason": f"写入素材失败：{exc}"})
                continue

            created += 1
            processed += 1
            logger.info(
                f"【素材同步】user={user_id} item={item_id} 已入库 "
                f"imgs={len(images)} desc_len={len(description or title)}"
            )
            # 最后一条之后无需再等待
            if processed < len(rows):
                await asyncio.sleep(THROTTLE_SECONDS)

        remaining = await self.count_missing(user_id=user_id, owner_scope=owner_scope)
        logger.info(
            f"【素材同步】user={user_id} 本批完成 新增={created} 失败={failed} "
            f"跳过={skipped} 剩余={remaining}{'（命中风控已中断）' if aborted else ''}"
        )
        return {
            "total_missing": total_missing,
            "processed": processed,
            "created": created,
            "failed": failed,
            "skipped": skipped,
            "remaining": remaining,
            "aborted": aborted,
            "errors": errors[:MAX_REPORTED_ERRORS],
        }
