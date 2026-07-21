"""LangGraph checkpointer 工厂。

支持两种后端：
- ``sqlite``：单进程本地方案，使用 ``langgraph-checkpoint-sqlite`` 的 ``AsyncSqliteSaver``。
- ``redis``：多进程共享方案，使用 ``langgraph-checkpoint-redis`` 的 ``AsyncRedisSaver``，
  复用项目现有 ``redis_url``（默认 db 0）。

后端通过运行期配置 ``checkpoint_backend`` 切换，默认 ``sqlite``；回退开关始终保留。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import aiosqlite
import structlog

if TYPE_CHECKING:
    from langgraph.checkpoint.base import BaseCheckpointSaver

logger = structlog.get_logger()


def _minutes_to_ttl(minutes: int) -> dict[str, Any] | None:
    """将分钟数转换为 RedisSaver 的 ttl 配置；0 或负数表示不过期。"""
    if minutes <= 0:
        return None
    return {
        "default_ttl": minutes,
        "refresh_on_read": False,
    }


async def get_sqlite_checkpointer_async(sqlite_path: str | Path) -> BaseCheckpointSaver:
    """创建并返回基于 SQLite 的异步 checkpointer 实例。

    调用方负责关闭返回的 saver.conn，或在 async context manager 中使用。
    """
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    path = Path(sqlite_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(str(path))
    saver = AsyncSqliteSaver(conn)
    logger.info(
        "async_sqlite_checkpointer_created",
        sqlite_path=str(path),
    )
    return saver


async def get_redis_checkpointer_async(
    redis_url: str,
    *,
    checkpoint_prefix: str = "checkpoint",
    ttl_minutes: int = 0,
) -> BaseCheckpointSaver:
    """创建并返回基于 Redis 的异步 checkpointer 实例。

    复用项目现有 Redis 连接串，不新增服务；key 使用 ``checkpoint_prefix`` 前缀，
    避免与现有缓存 / 锁 / Pub-Sub key 冲突。
    """
    from langgraph.checkpoint.redis.aio import AsyncRedisSaver

    ttl = _minutes_to_ttl(ttl_minutes)
    saver = AsyncRedisSaver(
        redis_url=redis_url,
        checkpoint_prefix=checkpoint_prefix,
        checkpoint_write_prefix=f"{checkpoint_prefix}_write",
        ttl=ttl,
    )
    logger.info(
        "async_redis_checkpointer_created",
        redis_url=redis_url.rsplit("@", 1)[-1],  # 隐藏可能包含的凭据
        checkpoint_prefix=checkpoint_prefix,
        ttl_minutes=ttl_minutes,
    )
    return saver


async def get_checkpointer(
    backend: Literal["sqlite", "redis"] | None = None,
    *,
    settings_service: Any | None = None,
    sqlite_path: str | Path | None = None,
    redis_url: str | None = None,
    redis_prefix: str | None = None,
    redis_ttl_minutes: int | None = None,
) -> BaseCheckpointSaver:
    """统一异步 checkpointer 工厂：按 ``checkpoint_backend`` 切换 SQLite / Redis。

    Args:
        backend: 显式指定后端；为 None 时读取 ``checkpoint_backend`` 运行期配置。
        settings_service: 用于读取运行期配置的 SettingsService 实例；为 None 时新建。
        sqlite_path: 显式传入 SQLite 路径；为 None 且 backend=sqlite 时读取运行期配置。
        redis_url: 显式传入 Redis 连接串；为 None 且 backend=redis 时读取 ``redis_url`` 运行期配置。
        redis_prefix: Redis key 前缀；为 None 时读取 ``checkpoint_redis_prefix`` 配置。
        redis_ttl_minutes: Redis 过期时间（分钟）；为 None 时读取 ``checkpoint_redis_ttl`` 配置。

    Returns:
        配置对应的后端 saver 实例。
    """
    if settings_service is None:
        from app.services.settings_service import SettingsService

        settings_service = SettingsService()

    if backend is None:
        backend = settings_service.get_runtime_value("checkpoint_backend")

    if backend == "redis":
        redis_url = redis_url or settings_service.get_runtime_value("redis_url")
        prefix = redis_prefix or settings_service.get_runtime_value("checkpoint_redis_prefix")
        ttl = redis_ttl_minutes if redis_ttl_minutes is not None else settings_service.get_runtime_value("checkpoint_redis_ttl")
        return await get_redis_checkpointer_async(
            redis_url=redis_url,
            checkpoint_prefix=prefix,
            ttl_minutes=ttl,
        )

    # 默认及显式 sqlite 均走 SQLite
    if sqlite_path is None:
        sqlite_path = settings_service.get_runtime_value("checkpoint_sqlite_path")
    return await get_sqlite_checkpointer_async(sqlite_path)


# 兼容性别名：早期代码直接调用 get_checkpointer_async
get_checkpointer_async = get_sqlite_checkpointer_async


def get_sync_sqlite_checkpointer(sqlite_path: str | Path) -> object:
    """同步 SQLite checkpointer（测试或特殊同步场景使用）。"""
    from langgraph.checkpoint.sqlite import SqliteSaver

    path = Path(sqlite_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return SqliteSaver(str(path))


async def close_checkpointer(saver: Any) -> None:
    """安全关闭 checkpointer 持有的连接。

    SQLite 关闭 aiosqlite 连接；Redis 若持有自建客户端则调用 aclose()，
    外部传入的 redis_client 不关闭。
    """
    if saver is None:
        return

    # SQLite: AsyncSqliteSaver 持有 conn
    conn = getattr(saver, "conn", None)
    if conn is not None:
        try:
            await conn.close()
            logger.info("async_sqlite_checkpointer_closed")
        except Exception as exc:  # noqa: BLE001
            logger.warning("close_sqlite_checkpointer_failed", error=str(exc))
        return

    # Redis: 仅关闭由 saver 自行创建的客户端
    owns = getattr(saver, "_owns_its_client", False)
    redis_client = getattr(saver, "_redis", None)
    if owns and redis_client is not None:
        try:
            await redis_client.aclose()
            logger.info("async_redis_checkpointer_closed")
        except Exception as exc:  # noqa: BLE001
            logger.warning("close_redis_checkpointer_failed", error=str(exc))
