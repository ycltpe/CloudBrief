import time
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import auth, chat, eval, health, index, kb_access
from app.api import metrics as metrics_api
from app.api.admin import router as admin_router
from app.logging_config import RequestIdMiddleware, configure_logging
from app.metrics import HTTP_REQUEST_DURATION, HTTP_REQUESTS_TOTAL
from app.stores.db import init_db
from app.stores.graph_store import GraphStore

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.services.settings_service import SettingsService

    settings_service = SettingsService()
    configure_logging(settings_service.get_runtime_value("log_level"))
    logger.info("app_starting", port=settings_service.get_runtime_value("backend_port"))
    init_db()
    logger.info("db_initialized")

    # GraphRAG：初始化 Neo4j 连接；失败不阻塞主服务启动
    graph_store = await GraphStore.create()
    if graph_store.is_available:
        await graph_store.initialize_schema()
    app.state.graph_store = graph_store
    logger.info("graph_store_ready", available=graph_store.is_available)

    yield

    await graph_store.close()
    logger.info("app_shutting_down")


app = FastAPI(
    title="CloudBrief 支持副驾",
    description="Enterprise RAG 内部知识问答系统",
    version="0.1.0",
    lifespan=lifespan,
)

# 中间件顺序：CORS 在最外层，request_id 在内层
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestIdMiddleware)


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000
    path = request.url.path
    method = request.method
    status_code = str(response.status_code)
    # 仅统计核心接口，避免 /metrics 自身循环
    if path.startswith(("/chat", "/index", "/admin", "/kb-access", "/eval")):
        HTTP_REQUESTS_TOTAL.labels(method=method, path=path, status_code=status_code).inc()
        HTTP_REQUEST_DURATION.labels(method=method, path=path).observe(duration_ms)
    return response


app.include_router(health.router)
app.include_router(auth.router)
app.include_router(admin_router)
app.include_router(chat.router)
app.include_router(index.router)
app.include_router(eval.router)
app.include_router(kb_access.router)
app.include_router(metrics_api.router)


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.error("unhandled_exception", error=str(exc), path=request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "服务器内部错误",
                "detail": {"exception": str(exc)},
            }
        },
    )


if __name__ == "__main__":
    import uvicorn

    from app.services.settings_service import SettingsService

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=SettingsService().get_runtime_value("backend_port"),
        reload=True,
    )
