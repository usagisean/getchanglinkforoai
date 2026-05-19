"""
FastAPI 应用入口
"""

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router as api_router
from app.config import settings

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="ChatGPT 支付长链生成器",
    docs_url=None,    # 生产环境关闭 Swagger UI
    redoc_url=None,
    openapi_url=None,
)

# 静态文件目录
STATIC_DIR = Path(__file__).parent / "static"

# 注册 API 路由
app.include_router(api_router)

# 挂载静态文件（CSS / JS / 图片等，如果后续需要拆分）
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def index():
    """返回主页面"""
    return FileResponse(
        str(STATIC_DIR / "index.html"),
        media_type="text/html",
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """全局异常处理，避免泄露内部错误细节"""
    logger.error("Unhandled exception: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "服务器内部错误"},
    )
