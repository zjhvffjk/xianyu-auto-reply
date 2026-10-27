"""本页素材最近一次发布摘要；与素材所属用户匹配，不访问平台。"""
from sqlalchemy import select, func, and_, or_
from common.models.publish_log import PublishLog
from common.models.xy_account import XYAccount
from common.services.publish_batch_jobs import beijing_iso
from common.utils.account_name import resolve_member_name, resolve_nickname
from common.services.xianyu_user_profile import cached_nickname_from_metadata
from common.utils.xianyu_utils import canonical_goofish_item_url


async def latest_material_publications(session, materials):
    if not materials:
        return {}
    owners = {}
    for m in materials:
        owners.setdefault(m['user_id'], []).append(m['id'])
    # 用创建时间及ID确定最近记录，不能让其他用户同素材ID的日志混入。
    ranked = select(PublishLog.id.label('id'), func.row_number().over(
        partition_by=(PublishLog.user_id, PublishLog.material_id),
        order_by=(PublishLog.created_at.desc(), PublishLog.id.desc())).label('position')).where(or_(
        *(and_(PublishLog.user_id == owner, PublishLog.material_id.in_(ids)) for owner, ids in owners.items())
    )).subquery()
    logs = (await session.execute(select(PublishLog).join(ranked, ranked.c.id == PublishLog.id)
        .where(ranked.c.position == 1))).scalars().all()
    if not logs:
        return {}
    accounts = (await session.execute(select(XYAccount).where(or_(
        *(and_(XYAccount.owner_id == l.user_id, XYAccount.account_id == l.account_id) for l in logs)
    )).order_by(XYAccount.id))).scalars().all()
    names = {}
    for a in accounts:
        member = resolve_member_name(a.cookie, a.display_name)
        nickname = resolve_nickname(cached_nickname_from_metadata(a.metadata_json), member)
        names[(a.owner_id, a.account_id)] = ' · '.join(dict.fromkeys(v for v in (member, nickname) if v)) or a.account_id
    return {l.material_id: dict(log_id=l.id, status=l.status, account_id=l.account_id,
        account_name=names.get((l.user_id, l.account_id), l.account_id), created_at=beijing_iso(l.created_at),
        error_message=l.error_message, item_id=l.item_id,
        item_url=canonical_goofish_item_url(l.item_id) if l.status == 'success' and str(l.item_id or '').isdigit() else None)
        for l in logs}
