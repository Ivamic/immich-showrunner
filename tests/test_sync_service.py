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
from showrunner.sync.executor import MARKER_NAME, Executor
from showrunner.sync.service import Output, SyncReport, run_sync, sync_outputs
from showrunner.targets.jellyfin.layout import JellyfinLayout
from showrunner.targets.kodi.layout import KodiLayout

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
    return sorted(
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if not p.is_dir() and p.name != MARKER_NAME
    )


def family() -> tuple[FakeImmich, UUID]:
    immich = FakeImmich()
    album = immich.add_album(1, "Family")
    immich.add_video(album, 1, "2023-06-10T09:00:00", description="First steps")
    immich.add_video(album, 2, "2024-07-15T14:32:00")
    return immich, album


FOLDER = "Family [imm-00000001]"
FILES = [
    f"{FOLDER}/Season 2023/20230610-090000 VID_1 [00000001].mp4",
    f"{FOLDER}/Season 2023/20230610-090000 VID_1 [00000001].nfo",
    f"{FOLDER}/Season 2024/20240715-143200 VID_2 [00000002].mp4",
    f"{FOLDER}/Season 2024/20240715-143200 VID_2 [00000002].nfo",
    f"{FOLDER}/tvshow.nfo",
]
THUMBS = [
    f"{FOLDER}/Season 2023/20230610-090000 VID_1 [00000001]-thumb.jpg",
    f"{FOLDER}/Season 2024/20240715-143200 VID_2 [00000002]-thumb.jpg",
]
ALL = sorted(FILES + THUMBS)


async def test_dry_run_writes_nothing(session: AsyncSession, out: Path) -> None:
    immich, _ = family()
    report = await sync(immich, session, None)
    assert not (out / MARKER_NAME).exists()
    assert report.dry_run and report.ok
    assert len(report.plan.actions) == 7
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
    assert report.ok and report.created == 7
    assert tree(out) == ALL
    assert os.readlink(out / FILES[0]) == "/mnt/immich/upload/owner/v1.mp4"
    assert "<title>First steps</title>" in (out / FILES[1]).read_text(encoding="utf-8")
    assert "<title>◈ Family</title>" in (out / FILES[4]).read_text(encoding="utf-8")
    assert report.changed_folders == {album: FOLDER}

    again = await sync(immich, session, out)
    assert again.plan.is_empty and again.changed_folders == {}
    assert tree(out) == ALL


@needs_links
async def test_quick_pass_skips_unchanged_albums(session: AsyncSession, out: Path) -> None:
    immich, album = family()
    await sync(immich, session, out)
    immich.requests.clear()
    report = await sync(immich, session, out, full=False)
    assert report.albums_read == 0 and report.plan.is_empty
    assert immich.requests == ["GET /api/albums"]
    assert tree(out) == ALL

    immich.add_video(album, 3, "2024-03-08T10:00:00")
    immich.touch(album, "2026-02-02T00:00:00.000Z")
    report = await sync(immich, session, out, full=False)
    assert report.albums_read == 1
    # The new video and its metadata, and the number of the later episode of the same season.
    assert (report.created, report.replaced) == (3, 1)
    later = (out / FILES[3]).read_text(encoding="utf-8")
    assert "<episode>2</episode>" in later


@needs_links
async def test_renamed_album_keeps_its_folder(session: AsyncSession, out: Path) -> None:
    immich, album = family()
    await sync(immich, session, out)
    immich.albums[album]["albumName"] = "Summers"
    report = await sync(immich, session, out)
    assert (report.created, report.replaced, report.removed) == (0, 1, 0)
    assert tree(out) == ALL
    assert "<title>◈ Summers</title>" in (out / FILES[4]).read_text(encoding="utf-8")


@needs_links
async def test_album_no_longer_shared_disappears_and_comes_back_in_the_same_folder(
    session: AsyncSession, out: Path
) -> None:
    immich, album = family()
    await sync(immich, session, out)
    saved_album, saved_videos = immich.albums.pop(album), immich.videos.pop(album)
    report = await sync(immich, session, out)
    assert report.ok and report.removed == 7
    assert tree(out) == [] and out.is_dir()
    # The output folder is never left empty: Jellyfin would keep the show otherwise.
    assert (out / MARKER_NAME).is_file()

    saved_album["albumName"] = "Renamed meanwhile"
    immich.albums[album], immich.videos[album] = saved_album, saved_videos
    await sync(immich, session, out)
    assert tree(out) == ALL


@needs_links
async def test_immich_error_removes_nothing(session: AsyncSession, out: Path) -> None:
    immich, _ = family()
    await sync(immich, session, out)
    for broken in ("/api/albums", "/api/search"):
        immich.broken = {broken: 500}
        with pytest.raises(ImmichError):
            await sync(immich, session, out)
        await session.rollback()
        assert tree(out) == ALL


@needs_links
async def test_mass_removal_is_held_until_forced(session: AsyncSession, out: Path) -> None:
    immich = FakeImmich()
    album = immich.add_album(1, "Big")
    for n in range(1, 31):
        immich.add_video(album, n, f"2024-01-{n:02d}T10:00:00")
    await sync(immich, session, out)
    assert len(tree(out)) == 91

    immich.albums.clear()  # the wrong API key: no album is visible
    report = await sync(immich, session, out)
    assert report.held and not report.ok
    assert report.plan.links_removed == 30
    assert len(tree(out)) == 91

    forced = await sync(immich, session, out, force=True)
    assert forced.ok and forced.removed == 91
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
    assert report.created == 6


@needs_links
async def test_moved_original_gets_a_new_link_target(session: AsyncSession, out: Path) -> None:
    immich, album = family()
    await sync(immich, session, out)
    immich.videos[album][0]["originalPath"] = "/data/library/2023/06/VID_1.mp4"
    report = await sync(immich, session, out)
    assert report.replaced == 1
    assert os.readlink(out / FILES[0]) == "/mnt/immich/library/2023/06/VID_1.mp4"


class SecondTarget(JellyfinLayout):
    """The Jellyfin layout under another name: a second output folder with its own registry."""

    name = "kodi"


@needs_links
async def test_two_targets_read_immich_once(session: AsyncSession, tmp_path: Path) -> None:
    immich, album = family()
    first, second = tmp_path / "jellyfin", tmp_path / "kodi"
    first.mkdir()
    second.mkdir()
    roots = [PurePosixPath("/mnt/immich")]
    outputs = [
        Output(JellyfinLayout(), Executor(first, roots), notify=True),
        Output(SecondTarget(), Executor(second, roots)),
    ]
    async with immich.client() as client:
        reports = await sync_outputs(
            immich=client, registry=Registry(session), outputs=outputs, options=OPTIONS
        )
    assert [r.target for r in reports] == ["jellyfin", "kodi"]
    assert tree(first) == ALL and tree(second) == ALL
    assert all(r.created == len(ALL) for r in reports)
    # Every album and every picture is read from Immich once for both targets.
    assert sum(r.endswith("/thumbnail") for r in immich.requests) == len(THUMBS)
    assert sum(r == "POST /api/search/metadata" for r in immich.requests) == 1
    registry = Registry(session)
    assert await registry.pending("jellyfin") == {album}
    assert await registry.pending("kodi") == set()

    # A file removed from one folder by hand is the business of that folder only.
    (second / FILES[4]).unlink()
    immich.add_video(album, 3, "2024-08-01T10:00:00")
    async with immich.client() as client:
        reports = await sync_outputs(
            immich=client, registry=Registry(session), outputs=outputs, options=OPTIONS
        )
    assert [r.created for r in reports] == [3, 3]
    assert not (second / FILES[4]).exists() and (first / FILES[4]).exists()


@needs_links
async def test_a_kodi_folder_alone(session: AsyncSession, out: Path) -> None:
    immich, album = family()
    anna = UUID("8800ba4a-52a0-4f68-944a-6587ea5ff3c2")
    immich.videos[album][1]["people"] = [{"id": str(anna), "name": "Anna"}]
    outputs = [Output(KodiLayout(), Executor(out, [PurePosixPath("/mnt/immich")]))]
    async with immich.client() as client:
        (report,) = await sync_outputs(
            immich=client, registry=Registry(session), outputs=outputs, options=OPTIONS
        )
    first, second = int("00000001", 16), int("00000002", 16)
    assert tree(out) == [
        f"{FOLDER}/.actors/Anna.jpg",
        f"{FOLDER}/Season 2023/2023-06-10 090000 [{first}]-thumb.jpg",
        f"{FOLDER}/Season 2023/2023-06-10 090000 [{first}].mp4",
        f"{FOLDER}/Season 2023/2023-06-10 090000 [{first}].nfo",
        f"{FOLDER}/Season 2024/2024-07-15 143200 [{second}]-thumb.jpg",
        f"{FOLDER}/Season 2024/2024-07-15 143200 [{second}].mp4",
        f"{FOLDER}/Season 2024/2024-07-15 143200 [{second}].nfo",
        f"{FOLDER}/tvshow.nfo",
    ]
    assert (out / FOLDER / ".actors" / "Anna.jpg").read_bytes() == f"JPEG face {anna}".encode()
    assert report.target == "kodi" and report.created == 8 and report.ok
    assert await Registry(session).entries("jellyfin") == []
