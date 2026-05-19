"""
简单密码认证服务。
通过环境变量 ACCESS_PASSWORD 设置密码，未设置则不启用认证。
认证状态通过 HttpOnly Cookie 维持。
"""

import hashlib
import hmac
import secrets
import time

from app.config import settings

# Cookie 名称
AUTH_COOKIE_NAME = "payurl_auth"


def is_auth_enabled() -> bool:
    """是否启用了密码认证"""
    return bool(settings.ACCESS_PASSWORD)


def verify_password(password: str) -> bool:
    """
    验证密码是否正确。
    使用 hmac.compare_digest 防止时序攻击。
    """
    if not is_auth_enabled():
        return True
    return hmac.compare_digest(
        password.encode("utf-8"),
        settings.ACCESS_PASSWORD.encode("utf-8"),
    )


def generate_auth_token() -> str:
    """
    生成认证 token，存入 Cookie。
    token = timestamp:hmac_signature
    """
    timestamp = str(int(time.time()))
    signature = _sign(timestamp)
    return f"{timestamp}:{signature}"


def verify_auth_token(token: str) -> bool:
    """验证 Cookie 中的认证 token 是否有效"""
    if not is_auth_enabled():
        return True
    if not token:
        return False
    parts = token.split(":", 1)
    if len(parts) != 2:
        return False
    timestamp, signature = parts
    # 验证签名
    if not hmac.compare_digest(signature, _sign(timestamp)):
        return False
    # 验证是否过期
    try:
        created_at = int(timestamp)
        if time.time() - created_at > settings.AUTH_COOKIE_MAX_AGE:
            return False
    except (ValueError, TypeError):
        return False
    return True


def _sign(data: str) -> str:
    """使用 SECRET_KEY 对数据进行 HMAC 签名"""
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        data.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
