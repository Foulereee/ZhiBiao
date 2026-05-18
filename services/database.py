from __future__ import annotations

import logging

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import event
from core.settings import get_settings

logger = logging.getLogger(__name__)

_engine = None
_async_session_factory = None
_db_ready = False


def get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        database_url = settings.get_database_url()
        logger.info(f"数据库类型: {settings.db_type}, 连接串: {database_url.split('@')[-1] if '@' in database_url else database_url}")
        engine_kwargs = {
            "echo": settings.debug,
            "pool_size": 20,
            "max_overflow": 10,
        }
        if settings.db_type == "mysql":
            engine_kwargs["pool_recycle"] = 3600
            engine_kwargs["pool_pre_ping"] = True
        _engine = create_async_engine(database_url, **engine_kwargs)
    return _engine


def async_session() -> async_sessionmaker[AsyncSession]:
    global _async_session_factory
    if _async_session_factory is None:
        _async_session_factory = async_sessionmaker(
            get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _async_session_factory


async def get_db() -> AsyncSession:
    if not _db_ready:
        raise HTTPException(status_code=503, detail="数据库暂不可用，请检查数据库服务是否已启动")
    session_factory = async_session()
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


def is_db_ready() -> bool:
    return _db_ready


async def init_db():
    global _db_ready
    from services.models import Base
    try:
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        _db_ready = True
        logger.info("数据库初始化成功")
    except Exception as e:
        logger.warning(f"数据库不可用，应用将以降级模式启动: {e}")
        _db_ready = False


async def close_db():
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
