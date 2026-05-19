"""
代理相关服务：格式校验、多协议尝试、IP 检测
"""

import json
import re
import urllib.error
import urllib.parse
import urllib.request

try:
    from curl_cffi import requests as curl_requests
except Exception:
    curl_requests = None

# IP 检测服务地址，按优先级排列
IP_CHECK_URLS = (
    "http://iprust.io/ip.json",
    "https://ipwho.is/",
    "https://api.myip.com/",
    "https://ipinfo.io/json",
)

_COMMON_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/136.0.0.0 Safari/537.36"
)


def normalize_proxy(value: str) -> str:
    """
    校验并标准化代理地址格式。
    支持 http / https / socks5 / socks5h 协议。
    """
    proxy = str(value or "").strip()
    if not proxy:
        return ""
    if "://" not in proxy:
        proxy = "http://" + proxy
    if not re.match(r"^(https?|socks4a?|socks5h?)://", proxy, re.I):
        raise ValueError("代理格式不支持，请使用 http://、https://、socks5:// 或 socks5h://")
    return proxy


def proxy_candidates(value: str) -> list[str]:
    """
    给定一个代理地址，生成多种协议变体用于自动尝试。
    例如输入 socks5://host:port，会额外尝试 socks5h / http / https。
    """
    proxy = normalize_proxy(value)
    if not proxy:
        return [""]

    match = re.match(r"^([a-z0-9+.-]+)://(.+)$", proxy, re.I)
    if not match:
        return [proxy]

    first_scheme = match.group(1).lower()
    rest = match.group(2)
    schemes = [first_scheme]
    for scheme in ("socks5h", "socks5", "http", "https"):
        if scheme not in schemes:
            schemes.append(scheme)
    return [f"{scheme}://{rest}" for scheme in schemes]


def check_proxy_ip(proxy: str = "") -> tuple[int, dict]:
    """检测代理出口 IP，优先使用 curl_cffi"""
    if curl_requests is not None:
        return _check_proxy_ip_curl_cffi(proxy)
    return _check_proxy_ip_urllib(proxy)


def _check_proxy_ip_curl_cffi(proxy: str = "") -> tuple[int, dict]:
    last_error = ""
    for candidate in proxy_candidates(proxy):
        proxies = {"http": candidate, "https": candidate} if candidate else None
        for url in IP_CHECK_URLS:
            try:
                response = curl_requests.get(
                    url,
                    headers={"Accept": "application/json", "User-Agent": _COMMON_UA},
                    impersonate="chrome136",
                    proxies=proxies,
                    timeout=15,
                )
                if response.status_code >= 400:
                    last_error = f"{url} returned {response.status_code}"
                    continue
                data = _normalize_ip_check_response(_parse_json(response.text))
                if isinstance(data, dict) and candidate:
                    data["proxy_used"] = candidate
                return 200, data
            except Exception as exc:
                last_error = str(exc)
    return 502, {"error": last_error or "代理检测失败"}


def _check_proxy_ip_urllib(proxy: str = "") -> tuple[int, dict]:
    last_error = ""
    for candidate in proxy_candidates(proxy):
        if candidate.lower().startswith(("socks4://", "socks4a://", "socks5://", "socks5h://")):
            last_error = "当前环境不支持 urllib 检测 socks 代理，请确保已安装 curl_cffi。"
            continue
        opener = None
        if candidate:
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({"http": candidate, "https": candidate})
            )
        for url in IP_CHECK_URLS:
            req = urllib.request.Request(
                url,
                headers={"Accept": "application/json", "User-Agent": _COMMON_UA},
            )
            try:
                open_func = opener.open if opener else urllib.request.urlopen
                with open_func(req, timeout=15) as resp:
                    text = resp.read().decode("utf-8", errors="replace")
                    data = _normalize_ip_check_response(_parse_json(text))
                    if isinstance(data, dict) and candidate:
                        data["proxy_used"] = candidate
                    return 200, data
            except Exception as exc:
                last_error = str(exc)
    return 502, {"error": last_error or "代理检测失败"}


def _normalize_ip_check_response(data: dict) -> dict:
    """将不同 IP 检测服务的返回统一为标准格式"""
    if not isinstance(data, dict):
        return {"error": "IP 检测服务返回异常"}

    connection = data.get("connection") if isinstance(data.get("connection"), dict) else {}

    return {
        "ip": data.get("ip") or data.get("query") or "",
        "country": data.get("country_long") or data.get("country") or data.get("country_name") or "",
        "country_code": (
            data.get("country_short")
            or data.get("country_code")
            or data.get("cc")
            or data.get("countryCode")
            or ""
        ),
        "region": data.get("region") or data.get("region_name") or "",
        "city": data.get("city") or "",
        "timezone": data.get("timezone") or "",
        "isp": connection.get("isp") or data.get("org") or data.get("isp") or "",
        "loc": data.get("loc") or "",
    }


def _parse_json(text: str) -> dict:
    try:
        return json.loads(text or "{}")
    except json.JSONDecodeError:
        return {"error": text or "返回不是 JSON"}
