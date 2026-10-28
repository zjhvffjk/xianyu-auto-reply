"""按当前账号权限启动和读取完整商品资料补全。"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api import deps
from app.services.account_service import AccountService
from app.services.catalog_detail_sync import CatalogDetailSyncService
from common.db.redis_client import get_redis_client
from common.models.user import User
from common.schemas.common import ApiResponse
from common.utils.auth_scope import resolve_owner_scope

router = APIRouter()


class DetailSyncRequest(BaseModel):
    item_ids: list[str] = Field(default_factory=list, max_length=50)


@router.post('/detail-sync/{cookie_id}', response_model=ApiResponse)
async def start_detail_sync(cookie_id: str, current_user: User = Depends(deps.get_current_active_user),
                            account_service: AccountService = Depends(deps.get_account_service),
                            payload: DetailSyncRequest | None = None):
    owner_id, _ = resolve_owner_scope(current_user)
    account = await account_service.get_account_for_user(owner_id, cookie_id)
    if not account:
        raise HTTPException(404, '店铺不存在或无权访问')
    try:
        job = await CatalogDetailSyncService(await get_redis_client()).start(account, payload.item_ids if payload else None)
        return ApiResponse(success=True, data=job, message='已在后台补全商品资料')
    except Exception:
        raise HTTPException(503, '商品资料补全服务暂不可用，请稍后重试')


@router.get('/detail-sync/{cookie_id}', response_model=ApiResponse)
async def get_detail_sync(cookie_id: str, job_id: str | None = Query(None, pattern='^[a-f0-9]{32}$'),
                          current_user: User = Depends(deps.get_current_active_user),
                          account_service: AccountService = Depends(deps.get_account_service)):
    owner_id, _ = resolve_owner_scope(current_user)
    account = await account_service.get_account_for_user(owner_id, cookie_id)
    if not account:
        raise HTTPException(404, '店铺不存在或无权访问')
    try:
        job = await CatalogDetailSyncService(await get_redis_client()).get(account.id, job_id)
        if job_id and not job:
            raise HTTPException(404, '资料补全进度已过期，已缓存资料仍保留，可重新补全')
        return ApiResponse(success=True, data=job)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, '无法读取资料补全进度，请稍后重试')
