from __future__ import annotations

import asyncio
import logging
import sqlite3
from pathlib import Path

from fastapi import FastAPI, Response, status, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

# Monkeypatch sqlite3.connect to increase default timeout
_original_sqlite3_connect = sqlite3.connect


def _patched_sqlite3_connect(*args, **kwargs):
    # Force timeout to be at least 10 seconds, even if Pyrogram sets it to 1
    if "timeout" in kwargs:
        if kwargs["timeout"] < 10:
            kwargs["timeout"] = 10
    else:
        kwargs["timeout"] = 30
    return _original_sqlite3_connect(*args, **kwargs)


sqlite3.connect = _patched_sqlite3_connect

from backend.api import router as api_router  # noqa: E402
from backend.core.config import get_settings  # noqa: E402
from backend.core.database import get_engine, get_session_local, init_engine  # noqa: E402
from backend.core.schema_migrator import upgrade_schema  # noqa: E402
from backend.core.rate_limit import limiter  # noqa: E402
import backend.models  # noqa: E402,F401
from backend.scheduler import (  # noqa: E402
    init_scheduler,
    shutdown_scheduler,
    sync_jobs,
)
from backend.services.users import ensure_admin  # noqa: E402
from backend.utils.paths import ensure_data_dirs  # noqa: E402


# Silence /health check logs
class HealthCheckFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return (
            "/health" not in msg
            and "/healthz" not in msg
            and "/readyz" not in msg
        )


logging.getLogger("uvicorn.access").addFilter(HealthCheckFilter())

settings = get_settings()

app = FastAPI(title=settings.app_name, version="0.1.0", debug=False)
app.state.ready = False
app.state.startup_error = None

# 注册速率限制
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# 全局异常处理器
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """捕获所有未处理的异常，记录详细日志但返回通用错误"""
    logger = logging.getLogger("backend.exceptions")
    logger.error(f"未处理的异常: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "服务器内部错误，请稍后重试"},
    )


app.add_middleware(GZipMiddleware, minimum_size=1000)



app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=settings.cors_allow_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API 路由必须在静态文件挂载之前注册，并使用 /api 前缀
app.include_router(api_router, prefix="/api")


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/healthz")
def health_checkz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
def ready_check(response: Response) -> dict[str, str]:
    if app.state.ready:
        return {"status": "ready"}
    response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    if app.state.startup_error:
        return {"status": "error"}
    return {"status": "starting"}


# 静态前端托管（Mode A: 单容器，FastAPI 提供静态文件）
# 挂载 Next.js 静态资源
next_static_dir = Path("/web/_next")
if next_static_dir.exists():
    app.mount(
        "/_next",
        StaticFiles(directory=str(next_static_dir)),
        name="nextjs_static",
    )


# Catch-all 路由：处理所有前端路由，返回 index.html
@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    """
    SPA fallback: 对于所有非 API 路由，返回 index.html
    这样刷新页面时不会 404
    """
    # 检查是否是静态文件请求
    web_dir = Path("/web")
    file_path = web_dir / full_path

    # 如果文件存在且不是目录，直接返回文件
    if file_path.exists() and file_path.is_file():
        return FileResponse(file_path)

    # 尝试添加 .html 后缀（Next.js 导出通常会生成 .html 文件）
    html_path = web_dir / f"{full_path}.html"
    if html_path.exists() and html_path.is_file():
        return FileResponse(html_path)

    # 否则返回 index.html（SPA 路由）
    index_path = web_dir / "index.html"
    if index_path.exists():
        return FileResponse(index_path)

    # 如果 index.html 也不存在，返回 404
    return {"detail": "Frontend not built"}


@app.on_event("startup")
async def on_startup() -> None:
    logger = logging.getLogger("backend.startup")

    # 验证 JWT 密钥来源
    import os
    if not os.getenv("APP_SECRET_KEY"):
        secret_file = settings.resolve_base_dir() / ".secret_key"
        if secret_file.exists():
            logger.warning(
                "使用自动生成的 JWT 密钥，生产环境请设置 APP_SECRET_KEY 环境变量"
            )
        else:
            logger.critical(
                "使用不安全的默认 JWT 密钥！生产环境必须设置 APP_SECRET_KEY 环境变量"
            )

    ensure_data_dirs(settings)
    init_engine()
    upgrade_schema(get_engine())
    with get_session_local()() as db:
        ensure_admin(db)
    await init_scheduler(sync_on_startup=False)

    async def _post_startup() -> None:
        try:
            await sync_jobs(schedule_range_catchup=True)
            app.state.ready = True
            app.state.startup_error = None
        except Exception as exc:
            app.state.startup_error = str(exc)
            logging.getLogger("backend.startup").error(
                f"Delayed scheduler sync failed: {exc}"
            )

    asyncio.create_task(_post_startup())


@app.on_event("shutdown")
def on_shutdown() -> None:
    shutdown_scheduler()
