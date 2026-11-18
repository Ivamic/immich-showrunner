# SPDX-License-Identifier: AGPL-3.0-or-later
"""Changes reach Kodi even when it was off: the shows stay queued for Kodi until it answers, and
the queue of Kodi is not the queue of Jellyfin."""

import json
import os
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import UUID

import httpx2
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from fake_immich import FakeImmich
from showrunner.config import parse_path_map
from showrunner.model.show import Options
from showrunner.runner import catch_up_kodi
from showrunner.store.registry import Registry
from showrunner.sync.executor import Executor
from showrunner.sync.service import Output, sync_outputs
from showrunner.targets.jellyfin.layout import JellyfinLayout
from showrunner.targets.kodi.client import KodiClient, KodiUnreachableError
from showrunner.targets.kodi.layout import KodiLayout

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(os.name == "nt", reason="symbolic links need Linux"),
]

OPTIONS = Options(path_mappings=parse_path_map("/data=/mnt/immich"))
OUTPUT = "smb://server/bridge/kodi"


class Kodi:
    """Knows the shows in `known` (album id -> Kodi id); `off` makes every request fail."""

    def __init__(self) -> None:
        self.known: dict[UUID, int] = {}
        self.off = False
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        if self.off:
            raise httpx2.ConnectError("refused")
        body = json.loads(request.content)
        self.calls.append((body["method"], body.get("params", {})))
        result: Any = "OK"
        if body["method"] == "VideoLibrary.GetTVShows":
            result = {
                "tvshows": [
                    {"tvshowid": i, "uniqueid": {"immich": str(a)}} for a, i in self.known.items()
                ]
            }
        return httpx2.Response(200, json={"id": body["id"], "jsonrpc": "2.0", "result": result})

    def client(self) -> KodiClient:
        return KodiClient("http://k.test", "kodi", "", transport=httpx2.MockTransport(self.handler))

    def methods(self) -> list[str]:
        return [method for method, _ in self.calls]


async def sync(immich: FakeImmich, session: AsyncSession, tmp_path: Path) -> None:
    roots = [PurePosixPath("/mnt/immich")]
    for name in ("jellyfin", "kodi"):
        (tmp_path / name).mkdir(exist_ok=True)
    outputs = [
        Output(JellyfinLayout(), Executor(tmp_path / "jellyfin", roots), notify=True),
        Output(KodiLayout(), Executor(tmp_path / "kodi", roots), notify=True),
    ]
    async with immich.client() as client:
        reports = await sync_outputs(
            immich=client, registry=Registry(session), outputs=outputs, options=OPTIONS
        )
    assert all(report.ok for report in reports)


async def tell(kodi: Kodi, session: AsyncSession) -> list[str]:
    async with kodi.client() as client:
        return await catch_up_kodi(client, Registry(session), OUTPUT)


async def test_changes_wait_for_kodi(session: AsyncSession, tmp_path: Path) -> None:
    immich = FakeImmich()
    album = immich.add_album(1, "Family")
    immich.add_video(album, 1, "2024-01-05T12:00:00")
    kodi = Kodi()
    await sync(immich, session, tmp_path)
    registry = Registry(session)
    assert await registry.pending("kodi") == {album} == await registry.pending("jellyfin")

    # Kodi is off: the show stays queued, also through a pass without changes.
    kodi.off = True
    with pytest.raises(KodiUnreachableError):
        await tell(kodi, session)
    await session.rollback()
    await sync(immich, session, tmp_path)
    assert await registry.pending("kodi") == {album}

    # Kodi is back: a new show is found by a scan; the queue of Jellyfin is left alone.
    kodi.off = False
    assert await tell(kodi, session) == ["Kodi: scanned the library"]
    assert await registry.pending("kodi") == set()
    assert await registry.pending("jellyfin") == {album}


async def test_changed_show_is_refreshed_and_hidden_show_is_removed(
    session: AsyncSession, tmp_path: Path
) -> None:
    immich = FakeImmich()
    kept = immich.add_album(1, "Kept")
    hidden = immich.add_album(2, "Hidden")
    immich.add_video(kept, 1, "2024-01-05T12:00:00")
    immich.add_video(hidden, 2, "2024-01-06T12:00:00")
    kodi = Kodi()
    await sync(immich, session, tmp_path)
    await tell(kodi, session)
    kodi.known = {kept: 21, hidden: 22}

    immich.albums[kept]["albumName"] = "Renamed"
    registry = Registry(session)
    row = (await registry.shows())[hidden]
    row.hidden = True  # hidden on the page: the album is still shared, but has no files
    await registry.commit()
    await sync(immich, session, tmp_path)

    kodi.calls.clear()
    done = await tell(kodi, session)
    assert kodi.methods() == [
        "Files.GetDirectory",
        "VideoLibrary.GetTVShows",
        "VideoLibrary.RemoveTVShow",
        "Files.GetDirectory",
        "Textures.GetTextures",
        "VideoLibrary.Clean",
        "VideoLibrary.Scan",
        "VideoLibrary.RefreshTVShow",
    ]
    assert kodi.calls[2][1] == {"tvshowid": 22}
    assert kodi.calls[4][1]["filter"]["value"] == f"{OUTPUT}/Kept [imm-00000001]/"
    assert kodi.calls[5][1]["directory"] == f"{OUTPUT}/Kept [imm-00000001]/"
    assert kodi.calls[7][1]["tvshowid"] == 21
    assert f"Kodi: removed the show of album {hidden}" in done
