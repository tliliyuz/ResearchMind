"""
ResearchMind FastAPI 入口。

- 创建 FastAPI 实例，配置 CORS 中间件
- 注册全局异常处理器
- 提供 /api/health 健康检查端点
- 后续 Phase 引入路由（auth / research）
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.core.exceptions import AppException
from app.middleware.auth_middleware import AuthMiddleware

logger = logging.getLogger(__name__)


# ── 生命周期管理 ──────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动 / 关闭时的生命周期事件。"""
    logger.info(f"🚀 {settings.APP_NAME} v0.1.0 启动中... (env={settings.ENV}, debug={settings.DEBUG})")
    yield
    logger.info(f"👋 {settings.APP_NAME} 已关闭")


# ── FastAPI 实例 ──────────────────────────────────────────

app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
    lifespan=lifespan,
)

# ── CORS 中间件 ───────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Auth 中间件（JWT 验证，写入 request.state） ──────────────

app.add_middleware(AuthMiddleware)

# ── 全局异常处理器 ───────────────────────────────────────


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Pydantic 请求校验失败 → E9003 (422)。"""
    errors = []
    for error in exc.errors():
        errors.append({
            "field": ".".join(str(loc) for loc in error["loc"]),
            "message": error["msg"],
            "type": error["type"],
        })
    return JSONResponse(
        status_code=422,
        content={
            "code": "E9003",
            "message": "请求参数校验失败",
            "detail": {
                "error_type": "ValidationError",
                "error_description": "请求参数校验失败，请检查输入",
                "errors": errors,
            },
        },
    )


@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    """AppException → 对应 HTTP 状态码。

    AppException 已通过 HTTPException.detail 携带完整响应体
    （{"code", "message", "detail"}），Starlette 对 dict 类型的 detail
    直接作为 JSON 响应体返回。
    """
    logger.warning(
        "业务异常: code=%s, message=%s, status=%d",
        exc.error_code, exc.error_message, exc.status_code,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.detail,
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """未预期异常 → E9001 (500)。"""
    logger.exception(f"未预料的服务器内部错误: {type(exc).__name__}: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "code": "E9001",
            "message": "服务器内部错误",
            "detail": {
                "error_type": "InternalError",
                "error_description": "服务器内部错误，请稍后重试",
            },
        },
    )


# ── 健康检查 ─────────────────────────────────────────────


@app.get("/api/health", tags=["系统"])
async def health_check():
    """健康检查端点。"""
    return {
        "code": "0",
        "message": "ok",
        "data": {"status": "healthy"},
    }


# ── 路由注册 ──────────────────────────────────────────────
from app.api import auth

app.include_router(auth.router, prefix="/api/auth")
# app.include_router(research.router, prefix="/api/research", tags=["研究任务"])  # Phase 2
