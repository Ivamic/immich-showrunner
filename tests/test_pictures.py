# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pictures from Immich: downloaded when new or changed there, never over a hand edit."""

import io
import os
from pathlib import Path, PurePosixPath
from uuid import UUID

import httpx2
import pytest
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from fake_immich import FakeImmich, asset_id, webp_picture
from showrunner.config import parse_path_map
from showrunner.immich.client import ImmichClient, NotPictureError
from showrunner.immich.pictures import PictureError, as_jpeg
from showrunner.model.show import Options
from showrunner.store.registry import Registry
from showrunner.sync.executor import Executor
from showrunner.sync.plan import ActionType, Entry, make_plan
from showrunner.sync.service import SyncReport, run_sync
from showrunner.targets.base import DesiredFile, FileKind, ImageSource
from showrunner.targets.jellyfin.layout import JellyfinLayout

pytestmark = pytest.mark.anyio
needs_links = pytest.mark.skipif(os.name == "nt", reason="symbolic links need Linux")

OPTIONS = Options(path_mappings=parse_path_map("/data=/mnt/immich"))
ALBUM = UUID("00000000-0000-4000-8000-0000000000a1")
FOLDER = "Family [imm-00000001]"
THUMB = f"{FOLDER}/Season 2024/20240105-120000 VID_1 [00000001]-thumb.jpg"
POSTER = f"{FOLDER}/poster.jpg"
JPEG_START = bytes.fromhex("ffd8")


# --- the plan ---------------------------------------------------------------------------------


def picture(version: str) -> DesiredFile:
    return DesiredFile(
        PurePosixPath("show/poster.jpg"),
        FileKind.IMAGE,
        ALBUM,
        image=ImageSource(UUID(int=7), version),
    )


def recorded(version: str, content_hash: str = "abc") -> Entry:
    return Entry(
        PurePosixPath("show/poster.jpg"),
        FileKind.IMAGE,
        ALBUM,
        content_hash=content_hash,
        source_version=version,
    )


def test_picture_is_compared_by_its_version_not_its_content() -> None:
    assert make_plan([picture("v1")], [recorded("v1")]).is_empty
    plan = make_plan([picture("v2")], [recorded("v1")])
    assert [a.type for a in plan.actions] == [ActionType.REPLACE]
    assert [a.type for a in make_plan([picture("v1")], []).actions] == [ActionType.CREATE]


def test_a_picture_needs_a_source() -> None:
    with pytest.raises(ValueError):
        DesiredFile(PurePosixPath("a/b.jpg"), FileKind.IMAGE, ALBUM)
    with pytest.raises(ValueError):
        DesiredFile(
            PurePosixPath("a/b.nfo"),
            FileKind.EPISODE_NFO,
            ALBUM,
            content=b"x",
            image=ImageSource(UUID(int=7), "v1"),
        )


# --- the client -------------------------------------------------------------------------------


def answering(content: bytes, media_type: str) -> httpx2.MockTransport:
    return httpx2.MockTransport(
        lambda request: httpx2.Response(200, content=content, headers={"content-type": media_type})
    )


async def test_a_jpeg_preview_is_kept_byte_for_byte() -> None:
    async with ImmichClient("http://i.test", "k", transport=answering(b"JPEG", "image/jpeg")) as c:
        assert await c.preview(UUID(int=1)) == b"JPEG"


@pytest.mark.parametrize("mode", ["RGB", "RGBA"])
async def test_a_webp_preview_becomes_jpeg(mode: str) -> None:
    transport = answering(webp_picture(mode), "image/webp")
    async with ImmichClient("http://i.test", "k", transport=transport) as c:
        content = await c.preview(UUID(int=1))
    with Image.open(io.BytesIO(content)) as picture:
        assert (picture.format, picture.size, picture.mode) == ("JPEG", (64, 36), "RGB")


async def test_what_is_not_a_picture_is_an_error() -> None:
    for content, media_type, message in [
        (b"<html>", "text/html", "not a picture"),
        (b"RIFF", "image/webp", "could not be read"),
    ]:
        async with ImmichClient(
            "http://i.test", "k", transport=answering(content, media_type)
        ) as c:
            with pytest.raises(NotPictureError, match=message):
                await c.preview(UUID(int=1))


async def test_a_person_picture_in_webp_becomes_jpeg_too() -> None:
    transport = answering(webp_picture(), "image/webp; charset=binary")
    async with ImmichClient("http://i.test", "k", transport=transport) as c:
        content = await c.person_picture(UUID(int=1))
    assert content.startswith(JPEG_START)


async def test_no_type_is_not_a_picture() -> None:
    with pytest.raises(PictureError, match="of no type"):
        await as_jpeg(b"x", "")


# --- a whole sync -----------------------------------------------------------------------------


@pytest.fixture
def out(tmp_path: Path) -> Path:
    folder = tmp_path / "output"
    folder.mkdir()
    return folder


def immich_with_one_video(*, cover: bool = False) -> tuple[FakeImmich, UUID]:
    immich = FakeImmich()
    album = immich.add_album(1, "Family")
    immich.add_video(album, 1, "2024-01-05T12:00:00")
    if cover:
        immich.albums[album]["albumThumbnailAssetId"] = str(asset_id(99))
    return immich, album


async def sync(immich: FakeImmich, session: AsyncSession, out: Path) -> SyncReport:
    async with immich.client() as client:
        return await run_sync(
            immich=client,
            registry=Registry(session),
            executor=Executor(out, [PurePosixPath("/mnt/immich")]),
            target=JellyfinLayout(),
            options=OPTIONS,
        )


def downloads(immich: FakeImmich) -> list[str]:
    return [r for r in immich.requests if r.endswith("/thumbnail")]


@needs_links
async def test_pictures_are_downloaded_once(session: AsyncSession, out: Path) -> None:
    immich, _ = immich_with_one_video(cover=True)
    await sync(immich, session, out)
    assert (out / THUMB).read_bytes() == f"JPEG {asset_id(1)} hash1".encode()
    assert (out / POSTER).read_bytes() == f"JPEG {asset_id(99)} cover".encode()
    assert len(downloads(immich)) == 2

    immich.requests.clear()
    report = await sync(immich, session, out)
    assert report.plan.is_empty
    assert downloads(immich) == []


@needs_links
async def test_new_preview_in_immich_is_downloaded_again(session: AsyncSession, out: Path) -> None:
    immich, album = immich_with_one_video()
    await sync(immich, session, out)
    immich.videos[album][0]["thumbhash"] = "hash2"
    immich.requests.clear()
    report = await sync(immich, session, out)
    assert report.replaced == 1
    assert (out / THUMB).read_bytes() == f"JPEG {asset_id(1)} hash2".encode()
    assert len(downloads(immich)) == 1


@needs_links
async def test_a_picture_replaced_by_hand_stays(session: AsyncSession, out: Path) -> None:
    immich, album = immich_with_one_video()
    await sync(immich, session, out)
    (out / THUMB).write_bytes(b"my own picture")
    immich.videos[album][0]["thumbhash"] = "hash2"
    report = await sync(immich, session, out)
    assert [str(o.action.path) for o in report.foreign] == [THUMB]
    assert (out / THUMB).read_bytes() == b"my own picture"


@needs_links
async def test_webp_previews_are_written_as_jpeg(session: AsyncSession, out: Path) -> None:
    immich, _ = immich_with_one_video(cover=True)
    immich.preview_type = "image/webp"
    report = await sync(immich, session, out)
    assert report.pictures_failed == []
    for path in (THUMB, POSTER):
        assert (out / path).read_bytes().startswith(JPEG_START)


@needs_links
async def test_a_picture_immich_can_not_give_does_not_stop_the_sync(
    session: AsyncSession, out: Path
) -> None:
    immich, _ = immich_with_one_video()
    immich.preview_type = "text/html"
    report = await sync(immich, session, out)
    assert report.ok
    assert report.created == 3  # tvshow.nfo, the link and its NFO
    assert len(report.pictures_failed) == 1 and "not a picture" in report.pictures_failed[0]
    assert not (out / THUMB).exists()

    # Tried again on the next pass, and taken once Immich gives it.
    immich.preview_type = "image/jpeg"
    report = await sync(immich, session, out)
    assert report.created == 1 and report.pictures_failed == []
    assert (out / THUMB).exists()


@needs_links
async def test_immich_down_while_downloading_changes_nothing(
    session: AsyncSession, out: Path
) -> None:
    immich, _ = immich_with_one_video()

    def down_for_pictures(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("/thumbnail"):
            raise httpx2.ConnectError("refused")
        return immich.handler(request)

    async with ImmichClient(
        "http://immich.test", "key", transport=httpx2.MockTransport(down_for_pictures)
    ) as client:
        with pytest.raises(Exception, match="did not answer"):
            await run_sync(
                immich=client,
                registry=Registry(session),
                executor=Executor(out, [PurePosixPath("/mnt/immich")]),
                target=JellyfinLayout(),
                options=OPTIONS,
            )
    assert [p.name for p in out.rglob("*") if p.is_file()] == []
