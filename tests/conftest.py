# SPDX-License-Identifier: AGPL-3.0-or-later
import os
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from showrunner.store.db import make_engine, make_session_factory, upgrade_async

TEST_DATABASE_URL = os.environ.get("SHOWRUNNER_TEST_DATABASE_URL", "")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    """An empty database with the tables of the latest migration. Everything in the test database
    is dropped first: never point SHOWRUNNER_TEST_DATABASE_URL at a database that is in use."""
    if not TEST_DATABASE_URL:
        pytest.skip("SHOWRUNNER_TEST_DATABASE_URL is not set")
    engine = make_engine(TEST_DATABASE_URL)
    async with engine.begin() as connection:
        await connection.execute(text("DROP SCHEMA public CASCADE"))
        await connection.execute(text("CREATE SCHEMA public"))
    await upgrade_async(TEST_DATABASE_URL)
    yield engine
    await engine.dispose()


@pytest.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    async with make_session_factory(engine)() as session:
        yield session
