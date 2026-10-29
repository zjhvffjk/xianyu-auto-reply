"""快递打单配置、核对、同步与取号；无平台发货或扣卡操作。"""
from fastapi import APIRouter, Depends, HTTPException, Query, Response, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, SecretStr, field_validator

from app.api.deps import get_current_active_user, get_current_admin_user, get_db_session
from app.services.waybill_platform_service import WaybillPlatformService
from app.services.waybill_authorization_service import WaybillAuthorizationService, parse_callback
from app.services.waybill_service import WaybillService, scoped_account
from common.models.user import UserRole
from common.services.waybill_client import WaybillRemoteError

router = APIRouter(prefix='/waybills', tags=['快递打单'])


class PlatformInput(BaseModel):
    app_key: str = Field(min_length=1, max_length=120, pattern=r'^[A-Za-z0-9_-]+$')
    app_secret: SecretStr | None = None

    @field_validator('app_secret')
    @classmethod
    def valid_secret(cls, value):
        if value is not None and (not value.get_secret_value().strip() or len(value.get_secret_value()) > 500):
            raise ValueError('AppSecret长度不正确')
        return value


class ConnectionInput(PlatformInput):
    login_user: str = Field(default='', max_length=200)
    mall_user_id: str = Field(default='', max_length=40, pattern=r'^\d*$')

    @field_validator('mall_user_id')
    @classmethod
    def canonical_mall_id(cls, value):
        if not value:
            return ''
        number = int(value)
        if not 1 <= number <= 9223372036854775807:
            raise ValueError('店铺ID必须是有效的正整数')
        return str(number)

class PreviewInput(BaseModel):
    order_nos: list[str] = Field(min_length=1, max_length=100)

    @field_validator('order_nos')
    @classmethod
    def unique_orders(cls, values):
        if any(not value or len(value) > 64 for value in values) or len(values) != len(set(values)):
            raise ValueError('订单号无效或重复')
        return values


class RecipientInput(BaseModel):
    name: str = Field(max_length=120)
    phone: str = Field(max_length=32)
    province: str = Field(max_length=60)
    city: str = Field(max_length=60)
    county: str = Field(max_length=60)
    address: str = Field(max_length=512)

    @field_validator('*')
    @classmethod
    def strip_fields(cls, value):
        return value.strip()


class SyncInput(BaseModel):
    order_no: str = Field(min_length=1, max_length=64)
    recipient: RecipientInput


class NumberInput(BaseModel):
    order_no: str = Field(min_length=1, max_length=64)
    template_id: str = Field(min_length=1, max_length=80)


async def service_for(account_id: str, response: Response,
                      db=Depends(get_db_session), user=Depends(get_current_active_user)):
    response.headers['Cache-Control'] = 'no-store'
    return WaybillService(db, await scoped_account(db, user, account_id), legacy_allowed=user.role == UserRole.ADMIN)


async def platform_for(response: Response, db=Depends(get_db_session), user=Depends(get_current_admin_user)):
    response.headers['Cache-Control'] = 'no-store'
    return WaybillPlatformService(db)


@router.get('/platform/config')
async def platform_config(service=Depends(platform_for)):
    return dict(success=True, data=await service.settings())


@router.put('/platform/config')
async def save_platform_config(data: PlatformInput, service=Depends(platform_for)):
    return dict(success=True, data=await service.save(data))


@router.post('/provider/callback')
async def authorization_callback(request: Request, db=Depends(get_db_session)):
    try:
        if request.headers.get('content-type', '').split(';')[0].lower() != 'application/x-www-form-urlencoded':
            raise HTTPException(415, '仅接受表单回调')
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 16384:
                raise HTTPException(413, '回调报文过大')
        result = await WaybillAuthorizationService(db).receive_callback(parse_callback(bytes(body)))
        return JSONResponse(result, headers={'Cache-Control': 'no-store'})
    except HTTPException as exc:
        return JSONResponse(dict(code=exc.status_code, message=exc.detail), status_code=exc.status_code,
                            headers={'Cache-Control': 'no-store'})


async def authorization_for(account_id: str, response: Response,
                            db=Depends(get_db_session), user=Depends(get_current_active_user)):
    response.headers['Cache-Control'] = 'no-store'
    return WaybillAuthorizationService(db, await scoped_account(db, user, account_id))


@router.get('/{account_id}/authorization')
async def authorization_status(service=Depends(authorization_for)):
    return dict(success=True, data=await service.status())


@router.post('/{account_id}/authorization')
async def start_authorization(service=Depends(authorization_for)):
    try:
        return dict(success=True, data=await service.start())
    except WaybillRemoteError as exc:
        raise HTTPException(502, str(exc)) from None


@router.delete('/{account_id}/authorization')
async def revoke_authorization(service=Depends(authorization_for)):
    return dict(success=True, data=await service.revoke())


@router.get('/{account_id}/settings')
async def settings(service=Depends(service_for)):
    return dict(success=True, data=await service.settings())


@router.put('/{account_id}/settings')
async def save_settings(data: ConnectionInput, service=Depends(service_for)):
    return dict(success=True, data=await service.save_settings(data))


@router.post('/{account_id}/templates')
async def templates(service=Depends(service_for)):
    try:
        return dict(success=True, data=await service.templates())
    except WaybillRemoteError as exc:
        raise HTTPException(502, str(exc)) from None


@router.post('/{account_id}/preview')
async def preview(data: PreviewInput, service=Depends(service_for)):
    return dict(success=True, data=await service.preview(data.order_nos))


@router.post('/{account_id}/sync')
async def sync(data: SyncInput, service=Depends(service_for)):
    return dict(success=True, data=await service.sync(data.order_no, data.recipient.model_dump()))


@router.post('/{account_id}/number')
async def number(data: NumberInput, service=Depends(service_for)):
    try:
        return dict(success=True, data=await service.number(data.order_no, data.template_id))
    except WaybillRemoteError as exc:
        raise HTTPException(502, str(exc)) from None


@router.post('/{account_id}/workbench')
async def workbench(service=Depends(service_for)):
    try:
        return dict(success=True, data=dict(url=await service.print_url()))
    except WaybillRemoteError as exc:
        raise HTTPException(502, str(exc)) from None


@router.get('/{account_id}/records')
async def records(page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=100),
                  service=Depends(service_for)):
    return dict(success=True, data=await service.records(page, page_size))
