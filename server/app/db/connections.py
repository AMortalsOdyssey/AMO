import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from neo4j import AsyncDriver, AsyncGraphDatabase
from pymilvus import MilvusClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

log = logging.getLogger("amo.db")

# ── PostgreSQL ──────────────────────────────────────────────

engine = create_async_engine(
    settings.pg_dsn,
    pool_size=settings.pg_pool_size,
    pool_pre_ping=True,
    connect_args={"server_settings": {"search_path": settings.pg_schema}},
)
async_session = async_sessionmaker(engine, expire_on_commit=False)


async def get_pg() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session


# ── Neo4j ───────────────────────────────────────────────────

_neo4j_driver: AsyncDriver | None = None


async def init_neo4j() -> AsyncDriver:
    global _neo4j_driver
    _neo4j_driver = AsyncGraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )
    await _neo4j_driver.verify_connectivity()
    return _neo4j_driver


async def close_neo4j():
    global _neo4j_driver
    if _neo4j_driver:
        await _neo4j_driver.close()
        _neo4j_driver = None


def get_neo4j() -> AsyncDriver:
    assert _neo4j_driver is not None, "Neo4j driver not initialized"
    return _neo4j_driver


# ── Zilliz (Milvus) ────────────────────────────────────────

_milvus_client: MilvusClient | None = None
_milvus_connect_task: asyncio.Task | None = None


def _build_milvus_client() -> MilvusClient:
    return MilvusClient(
        uri=settings.zilliz_uri,
        token=settings.zilliz_token,
        db_name=settings.zilliz_db,
    )


async def _connect_milvus() -> MilvusClient:
    global _milvus_client
    client = await asyncio.to_thread(_build_milvus_client)
    _milvus_client = client
    return client


async def init_milvus(timeout_seconds: float = 8.0) -> MilvusClient | None:
    global _milvus_client, _milvus_connect_task
    if _milvus_client is not None:
        return _milvus_client

    if _milvus_connect_task is None or _milvus_connect_task.done():
        _milvus_connect_task = asyncio.create_task(_connect_milvus())

    try:
        await asyncio.wait_for(asyncio.shield(_milvus_connect_task), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        log.warning(
            "Milvus connection timed out during startup; continuing without vector retrieval for now"
        )
        return None
    except Exception:
        _milvus_connect_task = None
        raise

    return _milvus_client


def close_milvus():
    global _milvus_client, _milvus_connect_task
    if _milvus_connect_task and not _milvus_connect_task.done():
        _milvus_connect_task.cancel()
    _milvus_connect_task = None
    if _milvus_client:
        _milvus_client.close()
        _milvus_client = None


def get_milvus() -> MilvusClient | None:
    return _milvus_client


# ── Lifecycle ───────────────────────────────────────────────

@asynccontextmanager
async def lifespan(_app):
    import logging
    log = logging.getLogger("amo")
    # Neo4j: allow startup even if unavailable
    try:
        await init_neo4j()
        log.info("Neo4j connected")
    except Exception as e:
        log.warning(f"Neo4j connection failed (graph API will be unavailable): {e}")
    # Milvus: allow startup even if unavailable
    try:
        if await init_milvus():
            log.info("Milvus connected")
        else:
            log.warning("Milvus unavailable at startup; vector retrieval will retry later")
    except Exception as e:
        log.warning(f"Milvus connection failed (vector search will be unavailable): {e}")
    yield
    await close_neo4j()
    close_milvus()
    await engine.dispose()
