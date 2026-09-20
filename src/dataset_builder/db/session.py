"""Async PostgreSQL connection and session factories."""

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine


def create_engine(database_url: str) -> AsyncEngine:
    if not database_url.startswith("postgresql+asyncpg://"):
        raise ValueError("DATABASE_URL must use the postgresql+asyncpg dialect")
    return create_async_engine(database_url, pool_pre_ping=True)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
