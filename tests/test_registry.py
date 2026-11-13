# SPDX-License-Identifier: AGPL-3.0-or-later
"""The registry on a real PostgreSQL. Needs SHOWRUNNER_TEST_DATABASE_URL; skipped without it."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import PurePosixPath
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from showrunner.store.registry import Registry
from showrunner.targets.base import DesiredFile, FileKind

pytestmark = pytest.mark.anyio

A1 = UUID("97769e09-f6ec-4d0b-86d0-3237df31f35b")
A2 = UUID("97769e09-0000-4000-8000-000000000002")
ASSET = UUID("712f0482-ba03-4739-a060-cea85f44e17d")


@pytest.fixture
async def registry(session: AsyncSession) -> AsyncIterator[Registry]:
    yield Registry(session)


def link(path: str = "show/Season 2024/v1.mp4", target: str = "/mnt/immich/v1.mp4") -> DesiredFile:
    return DesiredFile(
        PurePosixPath(path), FileKind.LINK, A1, ASSET, link_target=PurePosixPath(target)
    )


async def test_migrations_created_the_tables(session: AsyncSession) -> None:
    version = await session.scalar(text("SELECT version_num FROM alembic_version"))
    assert version == "0002"


async def test_pending_marks(registry: Registry) -> None:
    await registry.add_show(A1, "Summer")
    await registry.add_show(A2, "Winter")
    assert await registry.pending() == set()
    await registry.mark_pending({A1, A2})
    await registry.mark_pending(set())
    assert await registry.pending() == {A1, A2}
    await registry.clear_pending({A1})
    assert await registry.pending() == {A2}


async def test_show_folder_is_set_once(registry: Registry) -> None:
    row = await registry.add_show(A1, "Summer / lake")
    assert row.folder_name == "Summer lake [imm-97769e09]"
    assert row.season_mode == "year"
    await registry.commit()
    shows = await registry.shows()
    assert shows[A1].folder_name == "Summer lake [imm-97769e09]"
    assert shows[A1].album_updated_at is None


async def test_same_name_and_id_start_get_different_folders(registry: Registry) -> None:
    first = await registry.add_show(A1, "Summer")
    second = await registry.add_show(A2, "Summer")
    assert first.folder_name == "Summer [imm-97769e09]"
    assert second.folder_name == "Summer [imm-97769e09-00004000]"


async def test_record_update_forget(registry: Registry) -> None:
    await registry.add_show(A1, "Summer")
    nfo = DesiredFile(PurePosixPath("show/tvshow.nfo"), FileKind.SHOW_NFO, A1, content=b"<tvshow/>")
    await registry.record(link())
    await registry.record(nfo)
    await registry.commit()

    entries = {str(e.path): e for e in await registry.entries()}
    assert set(entries) == {"show/Season 2024/v1.mp4", "show/tvshow.nfo"}
    recorded = entries["show/Season 2024/v1.mp4"]
    assert recorded.kind is FileKind.LINK
    assert recorded.link_target == PurePosixPath("/mnt/immich/v1.mp4")
    assert (recorded.album_id, recorded.asset_id) == (A1, ASSET)
    assert entries["show/tvshow.nfo"].content_hash == nfo.content_hash
    assert entries["show/tvshow.nfo"].link_target is None

    await registry.record(link(target="/mnt/immich/moved/v1.mp4"))
    await registry.forget(PurePosixPath("show/tvshow.nfo"))
    await registry.commit()
    entries = {str(e.path): e for e in await registry.entries()}
    assert set(entries) == {"show/Season 2024/v1.mp4"}
    assert str(entries["show/Season 2024/v1.mp4"].link_target) == "/mnt/immich/moved/v1.mp4"


async def test_stamps(registry: Registry) -> None:
    await registry.add_show(A1, "Summer")
    updated = datetime(2026, 11, 13, 11, 44, 51, tzinfo=UTC)
    modified = datetime(2026, 11, 13, 11, 44, 52, tzinfo=UTC)
    await registry.set_stamps(A1, updated, modified)
    await registry.commit()
    row = (await registry.shows())[A1]
    assert (row.album_updated_at, row.assets_modified_at) == (updated, modified)
