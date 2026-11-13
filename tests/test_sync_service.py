# SPDX-License-Identifier: AGPL-3.0-or-later
"""A whole pass of the sync: a fake Immich, a real PostgreSQL and a real folder."""

import os
from pathlib import Path, PurePosixPath
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from fake_immich import FakeImmich
from showrunner.config import parse_path_map
from showrunner.immich.client import ImmichError
from showrunner.model.show import Options, SkipReason
from showrunner.store.registry import Registry
from showrunner.sync.executor import Executor
from showrunner.sync.service import SyncReport, run_sync
from showrunner.targets.jellyfin.layout import JellyfinLayout

pytestmark = pytest.mark.anyio
needs_links = pytest.mark.skipif(os.name == "nt", reason="symbolic links need Linux")

OPTIONS = Options(path_mappings=parse_path_map("/data=/mnt/immich"), show_prefix="◈ ")


@pytest.fixture
def out(tmp_path: Path) -> Path:
    folder = tmp_path / "output"
    folder.mkdir()
    return folder


async def sync(
    immich: FakeImmich, session: AsyncSession, out: Path | None, **kwargs: bool
) -> SyncReport:
    executor = Executor(out, [PurePosixPath("/mnt/immich")]) if out is not None else None
    async with immich.client() as client:
        return await run_sync(
            immich=client,
            registry=Registry(session),
            executor=executor,
            target=JellyfinLayout(),
            options=OPTIONS,
            **kwargs,
        )


def tree(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if not p.is_dir())


def family() -> tuple[FakeImmich, UUID]:
    immich = FakeImmich()
    album = immich.add_album(1, "Family")
    immich.add_video(album, 1, "2023-06-10T09:00:00", description="First steps")
    immich.add_video(album, 2, "2024-07-15T14:32:00")
    return immich, album


FOLDER = "Family [imm-00000001]"
FILES = [
    f"{FOLDER}/Season 2023/2023-06-10 VID_1 [00000001].mp4",
    f"{FOLDER}/Season 2023/2023-06-10 VID_1 [00000001].nfo",
    f"{FOLDER}/Season 2024/2024-07-15 VID_2 [00000002].mp4",
    f"{FOLDER}/Season 2024/2024-07-15 VID_2 [00000002].nfo",
    f"{FOLDER}/tvshow.nfo",
]


async def test_dry_run_writes_nothing(session: AsyncSession, out: Path) -> None:
    immich, _ = family()
    report = await sync(immich, session, None)
    assert report.dry_run and report.ok
    assert len(report.plan.actions) == 5
    assert (report.created, report.albums, report.albums_read) == (0, 1, 1)
    assert tree(out) == []
    await session.rollback()
    registry = Registry(session)
    assert await registry.shows() == {}
    assert await registry.entries() == []


@needs_links
async def test_album_becomes_a_show_and_a_second_pass_changes_nothing(
    session: AsyncSession, out: Path
) -> None:
    immich, album = family()
    report = await sync(immich, session, out)
    assert report.ok and report.created == 5
    assert tree(out) == FILES
    assert os.readlink(out / FILES[0]) == "/mnt/immich/upload/owner/v1.mp4"
    assert "<title>First steps</title>" in (out / FILES[1]).read_text(encoding="utf-8")
    assert "<title>◈ Family</title>" in (out / FILES[4]).read_text(encoding="utf-8")
    assert report.changed_folders == {album: FOLDER}

    again = await sync(immich, session, out)
    assert again.plan.is_empty and again.changed_folders == {}
    assert tree(out) == FILES


@needs_links
async def test_quick_pass_skips_unchanged_albums(session: AsyncSession, out: Path) -> None:
    immich, album = family()
    await sync(immich, session, out)
    immich.requests.clear()
    report = await sync(immich, session, out, full=False)
    assert report.albums_read == 0 and report.plan.is_empty
    assert immich.requests == ["GET /api/albums"]
    assert tree(out) == FILES

    immich.add_video(album, 3, "2024-03-08T10:00:00")
    immich.touch(album, "2026-02-02T00:00:00.000Z")
    report = await sync(immich, session, out, full=False)
    assert report.albums_read == 1
    # The new video and its metadata, and the number of the later episode of the same season.
    assert (report.created, report.replaced) == (2, 1)
    later = (out / FILES[3]).read_text(encoding="utf-8")
    assert "<episode>2</episode>" in later


@needs_links
async def test_renamed_album_keeps_its_folder(session: AsyncSession, out: Path) -> None:
    immich, album = family()
    await sync(immich, session, out)
    immich.albums[album]["albumName"] = "Summers"
    report = await sync(immich, session, out)
    assert (report.created, report.replaced, report.removed) == (0, 1, 0)
    assert tree(out) == FILES
    assert "<title>◈ Summers</title>" in (out / FILES[4]).read_text(encoding="utf-8")


@needs_links
async def test_album_no_longer_shared_disappears_and_comes_back_in_the_same_folder(
    session: AsyncSession, out: Path
) -> None:
    immich, album = family()
    await sync(immich, session, out)
    saved_album, saved_videos = immich.albums.pop(album), immich.videos.pop(album)
    report = await sync(immich, session, out)
    assert report.ok and report.removed == 5
    assert tree(out) == [] and out.is_dir()

    saved_album["albumName"] = "Renamed meanwhile"
    immich.albums[album], immich.videos[album] = saved_album, saved_videos
    await sync(immich, session, out)
    assert tree(out) == FILES


@needs_links
async def test_immich_error_removes_nothing(session: AsyncSession, out: Path) -> None:
    immich, _ = family()
    await sync(immich, session, out)
    for broken in ("/api/albums", "/api/search"):
        immich.broken = {broken: 500}
        with pytest.raises(ImmichError):
            await sync(immich, session, out)
        await session.rollback()
        assert tree(out) == FILES


@needs_links
async def test_mass_removal_is_held_until_forced(session: AsyncSession, out: Path) -> None:
    immich = FakeImmich()
    album = immich.add_album(1, "Big")
    for n in range(1, 31):
        immich.add_video(album, n, f"2024-01-{n:02d}T10:00:00")
    await sync(immich, session, out)
    assert len(tree(out)) == 61

    immich.albums.clear()  # the wrong API key: no album is visible
    report = await sync(immich, session, out)
    assert report.held and not report.ok
    assert report.plan.links_removed == 30
    assert len(tree(out)) == 61

    forced = await sync(immich, session, out, force=True)
    assert forced.ok and forced.removed == 61
    assert tree(out) == []


@needs_links
async def test_foreign_files_and_skipped_videos_are_reported(
    session: AsyncSession, out: Path
) -> None:
    immich, album = family()
    immich.add_video(album, 9, "2024-01-01T00:00:00", path="/elsewhere/v9.mp4")
    (out / FOLDER).mkdir()
    (out / FOLDER / "tvshow.nfo").write_text("written by hand", encoding="utf-8")
    report = await sync(immich, session, out)
    assert report.ok
    assert [(name, s.reason) for name, s in report.skipped] == [
        ("Family", SkipReason.NO_PATH_MAPPING)
    ]
    assert [str(o.action.path) for o in report.foreign] == [f"{FOLDER}/tvshow.nfo"]
    assert (out / FOLDER / "tvshow.nfo").read_text(encoding="utf-8") == "written by hand"
    assert report.created == 4


@needs_links
async def test_moved_original_gets_a_new_link_target(session: AsyncSession, out: Path) -> None:
    immich, album = family()
    await sync(immich, session, out)
    immich.videos[album][0]["originalPath"] = "/data/library/2023/06/VID_1.mp4"
    report = await sync(immich, session, out)
    assert report.replaced == 1
    assert os.readlink(out / FILES[0]) == "/mnt/immich/library/2023/06/VID_1.mp4"
