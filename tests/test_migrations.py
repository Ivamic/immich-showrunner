# SPDX-License-Identifier: AGPL-3.0-or-later
"""Migrations that change data: run from the version before them, on rows as they were."""

import asyncio
import uuid

import pytest
from alembic import command
from sqlalchemy import text

from conftest import TEST_DATABASE_URL
from showrunner.store.db import alembic_config, make_engine

pytestmark = pytest.mark.anyio


async def _fresh_at(revision: str) -> None:
    engine = make_engine(TEST_DATABASE_URL)
    async with engine.begin() as connection:
        await connection.execute(text("DROP SCHEMA public CASCADE"))
        await connection.execute(text("CREATE SCHEMA public"))
    await engine.dispose()
    await asyncio.to_thread(command.upgrade, alembic_config(TEST_DATABASE_URL), revision)


async def test_folders_of_shows_lose_the_separators_of_their_dates() -> None:
    if not TEST_DATABASE_URL:
        pytest.skip("SHOWRUNNER_TEST_DATABASE_URL is not set")
    await _fresh_at("0009")
    shows = {
        uuid.uuid4(): "2026-06_07 - Trip [imm-11111111]",
        uuid.uuid4(): "Summer [imm-22222222]",
        uuid.uuid4(): "Party 31.12.2025 [imm-33333333]",
    }
    engine = make_engine(TEST_DATABASE_URL)
    async with engine.begin() as connection:
        for album, folder in shows.items():
            await connection.execute(
                text("INSERT INTO show (album_id, folder_name) VALUES (:a, :f)"),
                {"a": album, "f": folder},
            )
    await asyncio.to_thread(command.upgrade, alembic_config(TEST_DATABASE_URL), "head")
    async with engine.connect() as connection:
        result = await connection.execute(text("SELECT folder_name FROM show"))
        folders = sorted(str(row[0]) for row in result.all())
    await engine.dispose()
    assert folders == [
        "20260607 - Trip [imm-11111111]",
        "Party 31122025 [imm-33333333]",
        "Summer [imm-22222222]",
    ]
