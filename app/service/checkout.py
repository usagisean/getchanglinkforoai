"""
支付会话创建服务：构建请求体、调用 OpenAI checkout API、解析返回
"""

import json
import re
import urllib.error
import urllib.parse
import urllib.request

from app.service.proxy import proxy_candidates

try:
    from curl_cffi import requests as curl_requests
except Exception:
    curl_requests = None

CHECKOUT_URL = "https://chatgpt.com/backend-api/payments/checkout"

_COMMON_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/136.0.0.0 Safari/537.36"
)


def extract_token(value: str) -> str:
    """
    从用户输入中提取 accessToken。
    支持直接粘贴 JWT、完整 session JSON、或包含 token 的文本。
    """
    text = str(value or "").strip()
    # 直接是 JWT 格式
    if re.fullmatch(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", text):
        return text
    # 尝试从 JSON 中提取
    try:
        j = json.loads(text)
        for key in ("accessToken", "access_token", "token"):
            if j.get(key):
                return j[key]
        # NOTE: 兼容嵌套结构 data.accessToken
        if isinstance(j.get("data"), dict) and j["data"].get("accessToken"):
            return j["data"]["accessToken"]
    except (json.JSONDecodeError, TypeError):
        pass
    # 正则匹配 JWT
    match = re.search(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", text)
    return match.group(0) if match else ""


def extract_promo_code(value: str) -> str:
    """从优惠码或优惠链接中提取 promo code"""
    text = str(value or "").strip()
    if not text:
        return ""
    match = re.search(r"[?&]promoCode=([^&#\s]+)", text, re.I)
    if match:
        return urllib.parse.unquote(match.group(1)).strip()
    return text


def build_checkout_payload(
    plan: str = "plus",
    mode: str = "hosted",
    country: str = "DE",
    currency: str = "EUR",
    use_promo: bool = True,
    promo_code: str = "",
    workspace_name: str = "linux-do",
    seat_quantity: int = 2,
) -> dict:
    """构建发送到 OpenAI checkout API 的请求体"""
    payload = {
        "plan_name": "chatgptteamplan" if plan == "team" else "chatgptplusplan",
        "billing_details": {
            "country": country.upper(),
            "currency": currency.upper(),
        },
        "checkout_ui_mode": mode,
    }

    if plan == "team" and use_promo and promo_code:
        payload["cancel_url"] = f"https://chatgpt.com/?promoCode={urllib.parse.quote(promo_code)}"
        payload["promo_code"] = promo_code
    else:
        payload["cancel_url"] = "https://chatgpt.com/#pricing"

    # NOTE: Plus 使用 promo_campaign 而非 promo_code
    if use_promo and plan != "team":
        payload["promo_campaign"] = {
            "promo_campaign_id": "plus-1-month-free",
            "is_coupon_from_query_param": True,
        }

    if plan == "team":
        try:
            seat_quantity = max(2, int(seat_quantity))
        except (TypeError, ValueError):
            seat_quantity = 2
        payload["team_plan_data"] = {
            "workspace_name": workspace_name,
            "price_interval": "month",
            "seat_quantity": seat_quantity,
        }

    return payload


def call_checkout(token: str, payload: dict, proxy: str = "") -> tuple[int, dict]:
    """调用 OpenAI checkout API，优先使用 curl_cffi"""
    if curl_requests is not None:
        return _call_checkout_curl_cffi(token, payload, proxy)
    return _call_checkout_urllib(token, payload, proxy)


def enrich_links(data: dict) -> dict:
    """为返回数据补充额外的链接格式"""
    if not isinstance(data, dict):
        return data
    session_id = data.get("checkout_session_id")
    processor = data.get("processor_entity")
    if session_id and processor and not data.get("chatgpt_checkout_url"):
        data["chatgpt_checkout_url"] = f"https://chatgpt.com/checkout/{processor}/{session_id}"
    for key in ("url", "stripe_hosted_url", "checkout_url"):
        value = data.get(key)
        if isinstance(value, str) and value.startswith("https://pay.openai.com/"):
            data["openai_payurl"] = value
            break
    return data


# ──────────────── 内部实现 ────────────────


def _request_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Origin": "https://chatgpt.com",
        "Referer": "https://chatgpt.com/",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "User-Agent": _COMMON_UA,
    }


def _looks_like_cloudflare_challenge(text: str) -> bool:
    lowered = (text or "").lower()
    return (
        "_cf_chl_opt" in lowered
        or "enable javascript and cookies to continue" in lowered
        or "cf-chl" in lowered
    )


def _parse_json(text: str) -> dict:
    try:
        return json.loads(text or "{}")
    except json.JSONDecodeError:
        return {"error": text or "返回不是 JSON"}


def _call_checkout_curl_cffi(token: str, payload: dict, proxy: str = "") -> tuple[int, dict]:
    last_error = ""
    for candidate in proxy_candidates(proxy):
        try:
            proxies = {"http": candidate, "https": candidate} if candidate else None
            response = curl_requests.post(
                CHECKOUT_URL,
                json=payload,
                headers=_request_headers(token),
                impersonate="chrome136",
                proxies=proxies,
                timeout=30,
            )
            text = response.text
            if _looks_like_cloudflare_challenge(text):
                last_error = "请求被 Cloudflare 拦截，请检查代理或网络环境。"
                continue
            data = _parse_json(text)
            if isinstance(data, dict) and candidate:
                data["proxy_used"] = candidate
            return response.status_code, data
        except Exception as exc:
            last_error = str(exc)
            continue
    return 502, {"error": last_error or "请求失败"}


def _call_checkout_urllib(token: str, payload: dict, proxy: str = "") -> tuple[int, dict]:
    candidates = proxy_candidates(proxy)
    last_error = ""
    for candidate in candidates:
        if candidate.lower().startswith(("socks4://", "socks4a://", "socks5://", "socks5h://")):
            last_error = "当前环境不支持 urllib 使用 socks 代理，请确保已安装 curl_cffi。"
            continue
        opener = None
        if candidate:
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({"http": candidate, "https": candidate})
            )
        req = urllib.request.Request(
            CHECKOUT_URL,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers=_request_headers(token),
        )
        try:
            open_func = opener.open if opener else urllib.request.urlopen
            with open_func(req, timeout=30) as resp:
                text = resp.read().decode("utf-8", errors="replace")
                data = _parse_json(text)
                if isinstance(data, dict) and candidate:
                    data["proxy_used"] = candidate
                return resp.status, data
        except urllib.error.HTTPError as exc:
            text = exc.read().decode("utf-8", errors="replace")
            if _looks_like_cloudflare_challenge(text):
                last_error = "普通请求被 Cloudflare 拦截，请确保已安装 curl_cffi。"
                continue
            data = _parse_json(text)
            if isinstance(data, dict) and candidate:
                data["proxy_used"] = candidate
            return exc.code, data
        except urllib.error.URLError as exc:
            last_error = str(exc.reason)
    return 502, {"error": last_error or "请求失败"}
