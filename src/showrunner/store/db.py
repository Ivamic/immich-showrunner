# SPDX-License-Identifier: AGPL-3.0-or-later
"""Connection to PostgreSQL and the migrations."""

import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def make_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(database_url, pool_pre_ping=True)


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


def alembic_config(database_url: str) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    # `%` is special in the values of this configuration.
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def upgrade(database_url: str) -> None:
    """Bring the database to the latest version. Not to be called from a running event loop."""
    command.upgrade(alembic_config(database_url), "head")


async def upgrade_async(database_url: str) -> None:
    await asyncio.to_thread(upgrade, database_url)
