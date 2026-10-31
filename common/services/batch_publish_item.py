"""批次单项执行，复用既有发布能力、地址池、发布器和商品同步。"""
from sqlalchemy import select
from common.db.session import async_session_maker
from common.models.xy_account import XYAccount
from common.models.product_material import ProductMaterial
from common.models.publish_log import PublishLog
from common.services.publish_address_service import PublishAddressService
from common.services.item_service import ItemService
from common.services.xianyu_publish_service import detect_publish_account_capability, ensure_publish_capability_reliable, publish_personal_single_item, publish_single_item


async def prepare_batch_item(user_id, account_id, material, log_id, static_root):
    async with async_session_maker() as session:
        account = (await session.execute(select(XYAccount).where(
            XYAccount.owner_id == user_id, XYAccount.account_id == account_id,
        ).order_by(XYAccount.id.desc()).limit(1))).scalars().first()
        if not account or not (account.cookie or '').strip():
            raise ValueError('账号不存在、无权使用或登录信息已移除')
        exists = (await session.execute(select(ProductMaterial.id).where(
            ProductMaterial.id == material['id'], ProductMaterial.user_id == user_id,
            ProductMaterial.is_deleted.is_(False),
        ))).scalar()
        if not exists:
            raise ValueError('素材已移除或无权使用，本项未发布')
        capability = ensure_publish_capability_reliable(await detect_publish_account_capability(
            cookie=account.cookie, account_id=account_id, owner_id=user_id))
        if not capability.get('success'):
            raise ValueError('账号发布能力暂不可用，请检查账号状态后重新创建任务')
        cookie = capability.get('cookies_str') or account.cookie
        account.cookie = cookie
        address = await PublishAddressService(session).resolve_publish_address(account_id, material)
        log = await session.get(PublishLog, log_id)
        for key, value in address.to_log_fields().items():
            setattr(log, key, value)
        await session.commit()
        return {'user_id': user_id, 'account_id': account_id, 'cookie': cookie,
                'material': address.apply_to_item_data(material),
                'is_fish_shop': bool(capability.get('is_fish_shop')), 'static_root': static_root}


async def publish_prepared_batch_item(context):
    publisher = publish_single_item if context['is_fish_shop'] else publish_personal_single_item
    request_started = False

    async def before_submit():
        nonlocal request_started
        request_started = True

    try:
        return await publisher(item_data=context['material'], cookie=context['cookie'],
            account_id=context['account_id'], owner_id=context['user_id'],
            static_root=context['static_root'], before_submit=before_submit)
    except Exception as exc:
        from loguru import logger
        logger.error('[批量发布] 单项异常 account={} stage={} exception={}',
                     context['account_id'], 'submit' if request_started else 'prepare', type(exc).__name__)
        if request_started:
            return {'success': False, 'unknown': True,
                    'message': '商品发布请求异常，结果待核查；请在发布日志记录核查结果，勿直接重发'}
        # 异常原文可能包含上传授权或地址查询参数；只回传阶段及固定提示。
        hint = '商品资料准备失败'
        if type(exc).__name__ == 'DirectPublishError':
            for word, label in [('地址', '宝贝所在地解析失败'), ('所在地', '宝贝所在地解析失败'),
                                ('图片', '商品图片处理失败'), ('视频', '商品视频处理失败'),
                                ('规格', '商品规格校验失败'), ('运费', '发货设置校验失败')]:
                if word in str(exc):
                    hint = label
                    break
        return {'success': False,
                'message': f'{hint}（{type(exc).__name__}），未调用商品发布接口，可检查素材后重新创建任务'}


async def sync_batch_item(context, result):
    async with async_session_maker() as session:
        account = (await session.execute(select(XYAccount).where(
            XYAccount.owner_id == context['user_id'], XYAccount.account_id == context['account_id'],
        ).order_by(XYAccount.id.desc()).limit(1))).scalars().first()
        if not account:
            return {'sync_status': 'skipped', 'sync_message': '账号已移除，未同步商品'}
        account.cookie = result.get('cookies_str') or context['cookie']
        await session.commit()
        if not result.get('success'):
            return {'sync_status': 'skipped', 'sync_message': '本项未确认成功，请核查平台商品'}
        import asyncio
        await asyncio.sleep(2)  # 沿用平台收录等待，减少刚发布商品漏同步。
        response = await ItemService(session).fetch_all_items_from_account(account=account)
        return {'sync_status': 'success' if response.get('success') else 'failed',
                'sync_message': '已自动同步店铺商品' if response.get('success') else '商品已发布，但自动同步失败，请稍后刷新商品管理',
                'sync_total_count': int(response.get('total_count') or 0),
                'sync_saved_count': int(response.get('saved_count') or 0)}
