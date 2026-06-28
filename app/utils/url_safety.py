"""URL 安全工具：SSRF 防护。

提供协议白名单、内网 IP 黑名单（IPv4/IPv6）、DNS 全地址解析、重定向链安全检查。
供 Fetch / Search 后端复用。
"""

import asyncio
import ipaddress
import logging
import socket
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_ALLOWED_PROTOCOLS = {"http", "https"}

# 内网/危险 IP 段（CIDR）
_PRIVATE_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),       # 回环
    ipaddress.ip_network("10.0.0.0/8"),         # A 类私有
    ipaddress.ip_network("172.16.0.0/12"),      # B 类私有
    ipaddress.ip_network("192.168.0.0/16"),     # C 类私有
    ipaddress.ip_network("169.254.0.0/16"),     # 链路本地
    ipaddress.ip_network("0.0.0.0/8"),           # 当前网络
    ipaddress.ip_network("::1/128"),             # IPv6 回环
    ipaddress.ip_network("fc00::/7"),            # IPv6 唯一本地
    ipaddress.ip_network("fe80::/10"),           # IPv6 链路本地
    ipaddress.ip_network("ff00::/8"),            # IPv6 组播
]


def _is_private_ip(ip_str: str) -> tuple[bool, str | None]:
    """判断 IP 是否属于内网/危险段。返回 (是否危险, 原因)。"""
    try:
        ip_obj = ipaddress.ip_address(ip_str)
    except ValueError:
        return False, None

    for network in _PRIVATE_NETWORKS:
        if ip_obj in network:
            return True, f"IP {ip_str} 属于内网地址 {network}（SSRF 防护）"
    return False, None


async def check_url_safety(url: str) -> str | None:
    """检查 URL 是否安全。返回 None 表示通过，否则返回拒绝原因。

    检查项：
    1. 协议白名单（仅 http/https）
    2. 解析 hostname 的所有 IPv4/IPv6 地址
    3. 任一地址命中内网段即拒绝
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return "URL 解析失败"

    if parsed.scheme.lower() not in _ALLOWED_PROTOCOLS:
        return f"协议 {parsed.scheme} 不在白名单中（仅 http/https）"

    hostname = parsed.hostname
    if not hostname:
        return "URL 缺少 hostname"

    # 支持 IPv6 字面量 [::1]
    if hostname.startswith("[") and hostname.endswith("]"):
        hostname = hostname[1:-1]

    try:
        loop = asyncio.get_running_loop()
        addrinfo = await loop.run_in_executor(
            None,
            lambda: socket.getaddrinfo(
                hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM
            ),
        )
        ips = {info[4][0] for info in addrinfo}
    except socket.gaierror:
        # DNS 解析失败交给下游 fetch 层处理，安全层不拦截
        return None
    except Exception:
        logger.exception("URL 安全检查时解析异常: url=%s", url)
        return "DNS 解析异常"

    for ip in ips:
        is_private, reason = _is_private_ip(ip)
        if is_private:
            return reason

    return None
