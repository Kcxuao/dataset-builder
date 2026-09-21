"""Async PostgreSQL and local SQLite connection/session factories."""

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine


def create_engine(database_url: str) -> AsyncEngine:
    if database_url.startswith("postgresql+asyncpg://"):
        return create_async_engine(database_url, pool_pre_ping=True)
    if database_url.startswith("sqlite+aiosqlite:///"):
        engine = create_async_engine(database_url, connect_args={"timeout": 30})

        @event.listens_for(engine.sync_engine, "connect")
        def configure_sqlite(connection: object, _record: object) -> None:
            cursor = connection.cursor()  # type: ignore[union-attr]
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()

        return engine
    raise ValueError("DATABASE_URL must use postgresql+asyncpg or sqlite+aiosqlite")


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
