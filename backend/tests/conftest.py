"""Tests run against a dedicated database, never the dev one.

Several suites TRUNCATE reference tables to isolate themselves. Pointed at
the development database that silently destroys ingested market data — hours
of API calls — so tests get their own database, created and migrated on
demand. Override with PRISM_TEST_DATABASE_URL if you want it elsewhere.
"""

import os
from collections.abc import AsyncIterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings


def _test_database_url() -> str:
    explicit = os.environ.get("PRISM_TEST_DATABASE_URL")
    if explicit:
        return explicit
    base = settings.async_database_url
    name = base.rsplit("/", 1)[-1]
    return base.rsplit("/", 1)[0] + f"/{name}_test"


TEST_DATABASE_URL = _test_database_url()


async def _create_database_if_missing() -> None:
    admin_url = TEST_DATABASE_URL.rsplit("/", 1)[0] + "/postgres"
    target = TEST_DATABASE_URL.rsplit("/", 1)[-1]

    engine = create_async_engine(
        admin_url, isolation_level="AUTOCOMMIT", poolclass=NullPool
    )
    async with engine.connect() as connection:
        exists = (
            await connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": target}
            )
        ).scalar()
        if not exists:
            await connection.execute(text(f'CREATE DATABASE "{target}"'))
    await engine.dispose()


def _migrate() -> None:
    """Run migrations. Must NOT be called from inside a running event loop —
    alembic/env.py starts its own via asyncio.run()."""
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", TEST_DATABASE_URL.replace("%", "%%"))
    command.upgrade(config, "head")


@pytest.fixture(scope="session", autouse=True)
def _prepare_database():
    """Create and migrate the test database once per run.

    Driven from a dedicated thread: pytest-asyncio already owns an event loop
    on the main thread, and both asyncpg and Alembic's async env.py want to
    start one of their own.
    """
    import asyncio
    import threading

    failure: list[BaseException] = []

    def run() -> None:
        try:
            asyncio.run(_create_database_if_missing())
            # Outside the loop above: alembic's env.py calls asyncio.run itself.
            _migrate()
        except BaseException as exc:  # noqa: BLE001 - re-raised on the main thread
            failure.append(exc)

    thread = threading.Thread(target=run)
    thread.start()
    thread.join()
    if failure:
        raise failure[0]


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()
