"""Request ID 中间件 — 为每个请求生成唯一 request_id，写入 contextvars + response header

对齐 ARCHITECTURE.md §5.5：跨请求传递 request_id，便于日志链路追踪。

使用纯 ASGI 中间件（非 BaseHTTPMiddleware），与 AuthMiddleware 保持一致的实现模式，
避免 BaseHTTPMiddleware 的流式响应和内存泄漏问题。
"""

from uuid import uuid4

from starlette.requests import Request
from starlette.responses import Response

from app.core.logging_config import request_id_var, user_id_var


class RequestIDMiddleware:
    """纯 ASGI 中间件：为每个请求生成唯一 request_id，写入 contextvars + response header。

    优先从客户端 X-Request-ID header 获取（支持链路透传），否则生成新 ID。
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)

        # 优先从客户端 header 获取（支持链路透传），否则生成新 ID
        rid = request.headers.get("X-Request-ID") or uuid4().hex[:12]
        token_rid = request_id_var.set(rid)

        # 尝试从 request.state 获取 user_id（AuthMiddleware 已注入）
        token_uid = None
        try:
            uid = getattr(request.state, "user_id", None)
            if uid is not None:
                token_uid = user_id_var.set(uid)
        except Exception:
            pass

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = dict(message.get("headers", []))
                headers[b"x-request-id"] = rid.encode()
                message["headers"] = list(headers.items())
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            request_id_var.reset(token_rid)
            if token_uid is not None:
                user_id_var.reset(token_uid)
