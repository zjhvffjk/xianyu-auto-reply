"""发布记录昵称快照；只读已授权账号的资料缓存，不调用平台接口。"""
from sqlalchemy import or_,select,update
from common.models.publish_log import PublishLog
from common.models.user import User,UserRole
from common.models.xy_account import XYAccount
from common.services.xianyu_user_profile import cached_nickname_from_metadata
from common.utils.account_name import is_masked_name


def publish_account_nickname(metadata):
    value=cached_nickname_from_metadata(metadata)
    return value[:120] if value and not is_masked_name(value) else None


async def load_publish_account_nicknames(session,user_id,account_ids):
    if not account_ids:
        return {}
    is_admin=select(User.id).where(User.id==user_id,User.role==UserRole.ADMIN).exists()
    rows=(await session.execute(select(XYAccount.account_id,XYAccount.metadata_json).where(
        XYAccount.account_id.in_(account_ids),or_(XYAccount.owner_id==user_id,is_admin),
    ))).all()
    return {account_id:publish_account_nickname(metadata) for account_id,metadata in rows}


async def retain_publish_account_nickname(session,account):
    nickname=publish_account_nickname(account.metadata_json)
    if nickname:
        await session.execute(update(PublishLog).where(
            PublishLog.user_id==account.owner_id,PublishLog.account_id==account.account_id,
            or_(PublishLog.account_nickname.is_(None),PublishLog.account_nickname==''),
        ).values(account_nickname=nickname,updated_at=PublishLog.updated_at))
