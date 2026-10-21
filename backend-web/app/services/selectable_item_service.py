"""
卡券可选商品服务

功能：
1. 为「卡券关联商品」选择弹窗提供轻量数据：已关联商品详情、全部匹配商品项
2. 仅返回选择场景所需的轻字段（item_id / title / price / 所属账号），避免一次性
   拉取全部商品的重字段（metadata、默认回复状态、卡券状态等）导致界面卡顿
3. 左侧待选列表复用现有 item_service.list_items_paginated（真分页 + 关键字搜索），
   本服务只补齐右侧「已选商品详情」与「全选筛选结果」两个轻量查询
4. 支持按店铺（账号）限定范围：卡券管理页切换店铺后，弹窗只列该店铺的商品；
   不传账号时行为与改造前一致（全部商品）
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import String, cast, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from common.models.card_item_relation import CardItemRelation
from common.models.xy_account import XYAccount
from common.models.xy_catalog_item import XYCatalogItem


class SelectableItemService:
    """卡券可选商品服务（轻量查询）"""

    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def _aggregate_rows(rows: List[Any]) -> List[Dict[str, Any]]:
        """把 (item_id, title, price, account_id) 行聚合成选择项

        同一 item_id 可能对应多条商品记录（同一商品挂在不同账号下），按 item_id
        去重保留一份标题/价格，并把所有出现过的所属账号收进 account_ids，
        供前端判断该商品是否属于当前店铺。
        """
        buckets: Dict[str, Dict[str, Any]] = {}
        for item_id, title, price, account_id in rows:
            if item_id is None:
                continue
            entry = buckets.get(item_id)
            if entry is None:
                entry = {"item_id": item_id, "title": title, "price": price, "account_ids": []}
                buckets[item_id] = entry
            if account_id and account_id not in entry["account_ids"]:
                entry["account_ids"].append(account_id)
        return list(buckets.values())

    async def get_associated_items(
        self,
        card_id: int,
        owner_id: Optional[int],
    ) -> List[Dict[str, Any]]:
        """获取卡券已关联商品的轻量详情（用于弹窗右侧「已选商品」展示）

        通过关联表 join 商品表取 title/price/所属账号；同一 item_id 可能对应多条
        商品记录（同一商品挂在不同账号下），按 item_id 去重保留其一，account_ids
        汇总全部所属账号。已删除商品（无商品记录）不在此返回，但选中态由
        get_card_item_ids 单独提供，保存时不丢失。

        Args:
            card_id: 卡券ID
            owner_id: 用户ID，None 表示管理员（不加 owner 过滤）
        """
        stmt = (
            select(
                XYCatalogItem.item_id,
                XYCatalogItem.title,
                XYCatalogItem.price,
                XYAccount.account_id,
            )
            .join(CardItemRelation, CardItemRelation.item_id == XYCatalogItem.item_id)
            .outerjoin(XYAccount, XYCatalogItem.account_pk == XYAccount.id)
            .where(CardItemRelation.card_id == card_id)
        )
        if owner_id is not None:
            stmt = stmt.where(XYCatalogItem.owner_id == owner_id)
        rows = await self.session.execute(stmt)
        return self._aggregate_rows(rows.all())

    async def get_all_selectable_item_keys(
        self,
        owner_id: Optional[int],
        search: str = "",
        cookie_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """获取全部匹配的可选商品轻量项（供「全选当前筛选结果」使用，不分页）

        搜索匹配 商品ID / 标题，仅在用户主动点「全选」时触发。
        传 cookie_id 时只返回该店铺的商品，避免切店铺后「全选」把其他店铺
        的商品一起选上。

        Args:
            owner_id: 用户ID，None 表示管理员（不加 owner 过滤）
            search: 关键字（商品ID / 标题）
            cookie_id: 账号ID（店铺），None 表示不限定
        """
        stmt = (
            select(
                XYCatalogItem.item_id,
                XYCatalogItem.title,
                XYCatalogItem.price,
                XYAccount.account_id,
            )
            .outerjoin(XYAccount, XYCatalogItem.account_pk == XYAccount.id)
        )
        conditions = []
        if owner_id is not None:
            conditions.append(XYCatalogItem.owner_id == owner_id)
        if cookie_id:
            conditions.append(XYAccount.account_id == cookie_id)
        if search and search.strip():
            kw = f"%{search.strip()}%"
            conditions.append(
                or_(
                    cast(XYCatalogItem.item_id, String).ilike(kw),
                    XYCatalogItem.title.ilike(kw),
                )
            )
        if conditions:
            stmt = stmt.where(*conditions)
        stmt = stmt.order_by(XYCatalogItem.created_at.desc())
        rows = await self.session.execute(stmt)
        return self._aggregate_rows(rows.all())
