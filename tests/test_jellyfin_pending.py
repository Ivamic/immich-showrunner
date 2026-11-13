# SPDX-License-Identifier: AGPL-3.0-or-later
"""Changes reach Jellyfin even when it was down: the shows stay marked until it answers."""

import os
from pathlib import Path, PurePosixPath
from uuid import UUID

import httpx2
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from fake_immich import FakeImmich
from showrunner.config import parse_path_map
from showrunner.model.show import Options
from showrunner.runner import catch_up_jellyfin
from showrunner.store.registry import Registry
from showrunner.sync.executor import Executor
from showrunner.sync.service import run_sync
from showrunner.targets.jellyfin.client import JellyfinClient, JellyfinUnreachableError
from showrunner.targets.jellyfin.layout import JellyfinLayout

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(os.name == "nt", reason="symbolic links need Linux"),
]

OPTIONS = Options(path_mappings=parse_path_map("/data=/mnt/immich"))
OUTPUT = PurePosixPath("/media/showrunner")


class Jellyfin:
    """Knows the shows in `known` (album id -> item id); `down` makes every request fail."""

    def __init__(self) -> None:
        self.known: dict[UUID, str] = {}
        self.down = False
        self.calls: list[str] = []

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        if self.down:
            raise httpx2.ConnectError("refused")
        path = request.url.path
        self.calls.append(f"{request.method} {path}")
        if path == "/Items":
            items = [{"Id": i, "ProviderIds": {"immich": str(a)}} for a, i in self.known.items()]
            return httpx2.Response(200, json={"Items": items})
        if path == "/Library/VirtualFolders":
            return httpx2.Response(200, json=[{"Locations": [str(OUTPUT)], "ItemId": "lib"}])
        return httpx2.Response(204)

    def client(self) -> JellyfinClient:
        return JellyfinClient("http://j.test", "k", transport=httpx2.MockTransport(self.handler))


async def sync(immich: FakeImmich, session: AsyncSession, out: Path) -> None:
    async with immich.client() as client:
        report = await run_sync(
            immich=client,
            registry=Registry(session),
            executor=Executor(out, [PurePosixPath("/mnt/immich")]),
            target=JellyfinLayout(),
            options=OPTIONS,
            notify_media_server=True,
        )
    assert report.ok


async def tell(jellyfin: Jellyfin, session: AsyncSession, visible: set[UUID]) -> list[str]:
    async with jellyfin.client() as client:
        return await catch_up_jellyfin(client, Registry(session), OUTPUT, visible)


async def test_changes_wait_for_jellyfin_and_are_told_once(
    session: AsyncSession, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    out.mkdir()
    immich = FakeImmich()
    album = immich.add_album(1, "Family")
    immich.add_video(album, 1, "2024-01-05T12:00:00")
    jellyfin = Jellyfin()

    await sync(immich, session, out)
    registry = Registry(session)
    assert await registry.pending() == {album}

    # Jellyfin is down: the mark stays.
    jellyfin.down = True
    with pytest.raises(JellyfinUnreachableError):
        await tell(jellyfin, session, {album})
    await session.rollback()
    assert await registry.pending() == {album}

    # A pass without changes does not lose the mark either.
    await sync(immich, session, out)
    assert await registry.pending() == {album}

    # Jellyfin is back: a new show needs a scan, then the mark is gone.
    jellyfin.down = False
    done = await tell(jellyfin, session, {album})
    assert done == ["scanned the library"]
    assert await registry.pending() == set()
    jellyfin.calls.clear()
    assert await tell(jellyfin, session, {album}) == []
    assert jellyfin.calls == []


async def test_renamed_show_is_refreshed_and_gone_show_is_scanned(
    session: AsyncSession, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    out.mkdir()
    immich = FakeImmich()
    kept = immich.add_album(1, "Kept")
    gone = immich.add_album(2, "Gone")
    immich.add_video(kept, 1, "2024-01-05T12:00:00")
    immich.add_video(gone, 2, "2024-01-06T12:00:00")
    jellyfin = Jellyfin()
    await sync(immich, session, out)
    await tell(jellyfin, session, {kept, gone})
    jellyfin.known = {kept: "series-kept", gone: "series-gone"}

    immich.albums[kept]["albumName"] = "Renamed"
    del immich.albums[gone]
    await sync(immich, session, out)
    assert await Registry(session).pending() == {kept, gone}

    jellyfin.calls.clear()
    await tell(jellyfin, session, {kept})
    assert jellyfin.calls == [
        "GET /Items",
        "GET /Library/VirtualFolders",
        "POST /Items/lib/Refresh",
        "POST /Items/series-kept/Refresh",
    ]
