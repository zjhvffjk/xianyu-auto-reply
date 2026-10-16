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
from sqlalchemy import func, or_, select, text as sqltext
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
# 从 remark 里取「源商品ID + 账号主键」
_REMARK_REF_RE = re.compile(r"item_id=(\d+).*?acc=(\d+)")


def _parse_source_ref(remark: Any) -> tuple[str | None, int | None]:
    """解析素材 remark，得到 (源闲鱼商品ID, 账号主键)。解析不出则返回 (None, None)。"""
    match = _REMARK_REF_RE.search(str(remark or ""))
    if not match:
        return None, None
    return match.group(1), int(match.group(2))


def _category_fields_from_form(form: dict[str, Any]) -> dict[str, Any]:
    """从商品详情接口的表单结构里提取类目字段。"""
    return {
        "cat_id": str(form.get("platform_category_id") or "").strip() or None,
        "cat_name": str(form.get("platform_category_name") or "").strip() or None,
        "channel_id": str(form.get("platform_channel_category_id") or "").strip() or None,
        "channel_name": str(form.get("platform_channel_category_name") or "").strip() or None,
        "leaf_id": str(form.get("platform_leaf_id") or "").strip() or None,
        "tb_id": str(form.get("platform_tb_category_id") or "").strip() or None,
        "path": [item for item in (form.get("platform_category_path") or []) if isinstance(item, dict)],
    }


def _category_fields_from_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    """从分类推荐接口的候选项里提取类目字段。"""
    return {
        "cat_id": str(candidate.get("cat_id") or "").strip() or None,
        "cat_name": str(candidate.get("cat_name") or "").strip() or None,
        "channel_id": str(candidate.get("channel_cat_id") or "").strip() or None,
        "channel_name": str(candidate.get("channel_cat_name") or "").strip() or None,
        "leaf_id": str(candidate.get("leaf_id") or "").strip() or None,
        "tb_id": str(candidate.get("tb_cat_id") or "").strip() or None,
        "path": [item for item in (candidate.get("path") or []) if isinstance(item, dict)],
    }


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

    async def _pick_account(self, *, user_id: int, owner_scope: int | None) -> XYAccount | None:
        """挑一个可用于调平台类目接口的账号（要求有 Cookie）。

        优先本人账号，避免管理员场景下误用其他分销的账号；
        本人无可用账号时才退回到 owner_scope 范围内的账号。
        """
        base = select(XYAccount).where(XYAccount.cookie.is_not(None)).where(XYAccount.cookie != "")
        own = (await self.session.execute(
            base.where(XYAccount.owner_id == user_id).limit(1)
        )).scalars().first()
        if own is not None:
            return own
        if owner_scope is not None and owner_scope != user_id:
            return (await self.session.execute(
                base.where(XYAccount.owner_id == owner_scope).limit(1)
            )).scalars().first()
        return None

    async def _resolve_category_by_cat_id(
        self,
        *,
        account: XYAccount,
        cat_id: str,
        cat_name: str = "",
        title: str = "",
        description: str = "",
    ) -> dict[str, Any] | None:
        """用已有的末级分类反查完整类目信息（channelCatId / tbCatId / 类目路径）。

        背景：闲鱼发布接口要求 catId + channelCatId 同时存在，缺 channelCatId 会报
        FAIL_BIZ_CHANNEL_CAT_ID_PATH_QUERY_ERROR；而商品详情接口对非鱼小铺账号不可用。

        传参要点（实测）：分类推荐接口按查询词的**语义**返回候选，
        - 用商品标题/描述查 → 候选会跑到语义最接近的类目上，目标 catId 常常不在候选里；
        - 用**类目名**查 → 目标类目稳定出现在候选中且 is_selected=true。
        因此优先用类目名当查询词，命中时要求 cat_id 与 cat_name 双匹配，避免张冠李戴。
        """
        # 延迟导入：避免模块级循环依赖
        from app.services.platform_category_service import PlatformCategoryService

        if not cat_id:
            return None
        wanted_id = str(cat_id).strip()
        wanted_name = str(cat_name or "").strip()
        query = wanted_name or (title or description).strip()[:200]
        if not query:
            return None
        try:
            data = await PlatformCategoryService().recommend(
                title=query,
                description=query,
                cookie=account.cookie,
                account_id=account.account_id,
                owner_id=account.owner_id,
                cat_id=wanted_id,
                cat_name=wanted_name,
            )
        except Exception as exc:  # noqa: BLE001 - 单条失败不影响整批
            logger.warning(f"【素材类目】catId={wanted_id} 反查类目失败: {exc!r}")
            return None

        candidates = [c for c in (data.get("candidates") or []) if isinstance(c, dict)]
        # 首选：cat_id 与 cat_name 双匹配（最可信）
        if wanted_name:
            for candidate in candidates:
                if (
                    str(candidate.get("cat_id") or "").strip() == wanted_id
                    and str(candidate.get("cat_name") or "").strip() == wanted_name
                ):
                    return candidate
        # 次选：仅 cat_id 匹配
        for candidate in candidates:
            if str(candidate.get("cat_id") or "").strip() == wanted_id:
                return candidate
        return None

    async def _resolve_via_item_detail(
        self,
        *,
        account: XYAccount,
        item_id: str,
    ) -> dict[str, Any] | None:
        """首选路径：直接调商品详情接口，取平台认可的完整类目。

        源商品仍在售时这是最可靠的方式（详情里带的就是平台当前生效的类目）。
        失败返回 None，由调用方退化到「按类目名反查」。
        """
        if not item_id:
            return None
        try:
            result = await fetch_seller_item_edit_detail(
                account_id=account.account_id,
                cookie=account.cookie,
                item_id=item_id,
                owner_id=account.owner_id,
            )
        except Exception as exc:  # noqa: BLE001 - 单条失败不影响整批
            logger.warning(f"【素材类目】item={item_id} 详情接口异常: {exc!r}")
            return None

        # 平台可能刷新 Cookie，回写以免下次仍用旧值
        new_cookie = str(result.get("cookies_str") or "").strip()
        if new_cookie and new_cookie != (account.cookie or "").strip():
            account.cookie = new_cookie

        if not result.get("success"):
            return None
        form = ((result.get("data") or {}).get("form") or {})
        return form if form.get("platform_category_id") else None

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
            # 类目相关字段：详情接口能给出就直接用，给不出再按 catId 反查补全。
            # 发布接口要求 catId + channelCatId 同时存在，缺 channelCatId 会被平台拒绝。
            channel_category_id: str | None = None
            channel_category_name: str | None = None
            leaf_id: str | None = None
            tb_category_id: str | None = None
            category_path: list[dict[str, Any]] = []
            category_attributes: list[dict[str, Any]] = []
            category_source = "manual"

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
                    # 详情接口本来就返回完整类目，之前只取了 catId/名称，导致建出来的素材缺
                    # channelCatId 无法发布 —— 这里全部带上。
                    channel_category_id = (
                        str(form.get("platform_channel_category_id") or "").strip() or None
                    )
                    channel_category_name = (
                        str(form.get("platform_channel_category_name") or "").strip() or None
                    )
                    leaf_id = str(form.get("platform_leaf_id") or "").strip() or None
                    tb_category_id = str(form.get("platform_tb_category_id") or "").strip() or None
                    category_path = [
                        item for item in (form.get("platform_category_path") or [])
                        if isinstance(item, dict)
                    ]
                    category_attributes = [
                        item for item in (form.get("platform_attributes") or [])
                        if isinstance(item, dict)
                    ]
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

            # 详情接口不可用（如非鱼小铺账号）或未返回渠道类目时，用快照里的 catId 反查一次。
            # 不做这一步，同步出来的素材会缺少 channelCatId，发布必被平台拒绝。
            if category_id and not channel_category_id and account is not None:
                resolved = await self._resolve_category_by_cat_id(
                    account=account,
                    cat_id=category_id,
                    cat_name=category_name or "",
                    title=title,
                    description=description or title,
                )
                if resolved:
                    channel_category_id = (
                        str(resolved.get("channel_cat_id") or "").strip() or channel_category_id
                    )
                    channel_category_name = (
                        str(resolved.get("channel_cat_name") or "").strip()
                        or channel_category_name
                    )
                    leaf_id = str(resolved.get("leaf_id") or "").strip() or leaf_id
                    tb_category_id = (
                        str(resolved.get("tb_cat_id") or "").strip() or tb_category_id
                    )
                    resolved_path = [
                        item for item in (resolved.get("path") or []) if isinstance(item, dict)
                    ]
                    if resolved_path:
                        category_path = resolved_path
                    resolved_name = str(resolved.get("cat_name") or "").strip()
                    if resolved_name:
                        category_name = resolved_name
                    category_source = "recommendation"
                await asyncio.sleep(THROTTLE_SECONDS)

            material = ProductMaterial(
                user_id=user_id,
                title=title,
                description=(description or title)[:MAX_DESC],
                price=parse_price(row.price),
                category=category_name,
                platform_category_id=category_id,
                platform_category_name=category_name,
                platform_channel_category_id=channel_category_id,
                platform_channel_category_name=channel_category_name,
                platform_leaf_id=leaf_id,
                platform_tb_category_id=tb_category_id,
                platform_category_path=category_path,
                platform_attributes=category_attributes,
                category_source=category_source,
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

    # ---------- 历史素材类目回填 ----------

    def _category_missing_base(self, *, user_id: int):
        """「有 catId、缺 channelCatId」的素材 —— 这批发不出去，需要补类目。"""
        return (
            select(ProductMaterial)
            .where(ProductMaterial.user_id == user_id)
            .where(ProductMaterial.platform_category_id.is_not(None))
            .where(ProductMaterial.platform_category_id != "")
            .where(
                or_(
                    ProductMaterial.platform_channel_category_id.is_(None),
                    ProductMaterial.platform_channel_category_id == "",
                )
            )
        )

    async def count_category_missing(self, *, user_id: int) -> int:
        """统计还差多少条素材缺渠道类目。"""
        stmt = select(func.count()).select_from(
            self._category_missing_base(user_id=user_id).subquery()
        )
        return int((await self.session.execute(stmt)).scalar() or 0)

    async def preview_category_backfill(self, *, user_id: int) -> dict[str, Any]:
        """类目回填前的预览（纯统计，不调平台接口）。"""
        return {"missing": await self.count_category_missing(user_id=user_id)}

    async def backfill_categories(
        self,
        *,
        user_id: int,
        owner_scope: int | None = None,
        limit: int = DEFAULT_BATCH_LIMIT,
    ) -> dict[str, Any]:
        """给历史素材补渠道类目（channelCatId / tbCatId / 类目路径）。

        两条路径，按可靠性排序：
        1. 源商品详情接口（源商品仍在售时最准，详情里就是平台当前生效的类目）；
        2. 用素材已有的类目名调分类推荐接口反查（源商品已下架时的退路）。

        两条都不通时如实记为失败，提示用户在素材编辑里手动重选分类 —— 宁可留空，
        也不猜一个类目写进去，否则会发到错误的分类下。

        Args:
            user_id: 素材归属用户。
            owner_scope: 取账号时的归属过滤（管理员为 None）。
            limit: 本次最多处理条数，前端循环调用直到 remaining 归零。
        """
        batch_limit = max(1, min(int(limit or DEFAULT_BATCH_LIMIT), MAX_BATCH_LIMIT))
        total = await self.count_category_missing(user_id=user_id)
        if total <= 0:
            return {
                "total_missing": 0, "processed": 0, "updated": 0, "failed": 0,
                "remaining": 0, "errors": [],
            }

        rows = (await self.session.execute(
            self._category_missing_base(user_id=user_id).limit(batch_limit)
        )).scalars().all()

        # 详情接口必须用「商品所属账号」；类目反查是平台级查询，任意有 Cookie 的账号都行
        refs = [_parse_source_ref(material.remark) for material in rows]
        accounts = await self._load_accounts(pk for _, pk in refs if pk)
        fallback_account = await self._pick_account(user_id=user_id, owner_scope=owner_scope)
        if fallback_account is None and not accounts:
            return {
                "total_missing": total, "processed": 0, "updated": 0, "failed": 0,
                "remaining": total,
                "errors": [{"item_id": "", "reason": "当前没有带 Cookie 的闲鱼账号可用于补全类目"}],
            }

        updated = 0
        failed = 0
        errors: list[dict[str, str]] = []

        for material, (src_item_id, acc_pk) in zip(rows, refs):
            cat_id = str(material.platform_category_id or "").strip()
            title = str(material.title or "").strip()
            description = str(material.description or "").strip()
            applied: dict[str, Any] | None = None
            via = ""

            owner_account = accounts.get(acc_pk) if acc_pk else None

            # 路径 1：源商品详情
            if src_item_id and owner_account is not None and (owner_account.cookie or "").strip():
                form = await self._resolve_via_item_detail(
                    account=owner_account, item_id=src_item_id
                )
                if form:
                    applied = _category_fields_from_form(form)
                    via = "商品详情"
                await asyncio.sleep(THROTTLE_SECONDS)

            # 路径 2：按已有类目名反查
            if applied is None:
                host = fallback_account or owner_account
                if host is not None:
                    candidate = await self._resolve_category_by_cat_id(
                        account=host,
                        cat_id=cat_id,
                        cat_name=str(material.platform_category_name or "").strip(),
                        title=title,
                        description=description,
                    )
                    if candidate:
                        applied = _category_fields_from_candidate(candidate)
                        via = "类目反查"
                    await asyncio.sleep(THROTTLE_SECONDS)

            if applied is None or not applied.get("channel_id"):
                failed += 1
                errors.append({
                    "item_id": str(material.source_item_id or material.id),
                    "reason": "未能取到渠道类目，请在素材编辑里手动重新选择分类",
                })
                continue

            material.platform_channel_category_id = applied.get("channel_id")
            material.platform_channel_category_name = applied.get("channel_name")
            material.platform_leaf_id = applied.get("leaf_id") or material.platform_leaf_id
            material.platform_tb_category_id = (
                applied.get("tb_id") or material.platform_tb_category_id
            )
            if applied.get("path"):
                material.platform_category_path = applied["path"]
            if applied.get("cat_id"):
                material.platform_category_id = applied["cat_id"]
            if applied.get("cat_name"):
                material.platform_category_name = applied["cat_name"]
                material.category = applied["cat_name"]
            material.category_source = "recommendation"
            try:
                await self.session.commit()
                updated += 1
                logger.info(
                    f"【素材类目】id={material.id} 已补全（{via}）"
                    f" chan={material.platform_channel_category_id}"
                    f" tb={material.platform_tb_category_id}"
                )
            except Exception as exc:  # noqa: BLE001 - 单条失败不影响整批
                await self.session.rollback()
                failed += 1
                errors.append({
                    "item_id": str(material.source_item_id or material.id),
                    "reason": f"写入失败：{exc}",
                })

        remaining = await self.count_category_missing(user_id=user_id)
        logger.info(
            f"【素材类目】user={user_id} 本批完成 已补={updated} 失败={failed} 剩余={remaining}"
        )
        return {
            "total_missing": total, "processed": len(rows), "updated": updated,
            "failed": failed, "remaining": remaining,
            "errors": errors[:MAX_REPORTED_ERRORS],
        }
