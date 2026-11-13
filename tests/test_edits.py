# SPDX-License-Identifier: AGPL-3.0-or-later
"""Edits made on the page: titles, plots, order, hidden episodes and shows."""

import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import UUID

import httpx2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from fake_immich import FakeImmich, album_id, asset_id
from showrunner.app import create_app
from showrunner.config import Settings, parse_path_map
from showrunner.immich.models import Album, Asset, ExifInfo
from showrunner.model.show import EpisodeEdit, Options, ShowEdit, build_show
from showrunner.store.registry import Registry
from showrunner.sync.executor import Executor
from showrunner.sync.plan import Entry, make_plan
from showrunner.sync.service import SyncReport, run_sync
from showrunner.targets.base import FileKind
from showrunner.targets.jellyfin.layout import JellyfinLayout
from test_auth import APP_KEY, SECRET, Immich

OPTIONS = Options(path_mappings=parse_path_map("/data=/mnt/immich"), show_prefix="◈ ")
ALBUM = UUID(int=1)


def video(n: int, when: str, description: str = "") -> Asset:
    return Asset.model_validate(
        {
            "id": asset_id(n),
            "type": "VIDEO",
            "owner_id": UUID(int=9),
            "original_path": f"/data/v{n}.mp4",
            "original_file_name": f"V{n}.mp4",
            "local_date_time": datetime.fromisoformat(when).replace(tzinfo=UTC),
            "updated_at": datetime(2026, 1, 1, tzinfo=UTC),
            "exif_info": ExifInfo(description=description),
        }
    )


ALBUM_ROW = Album(id=ALBUM, album_name="Family", updated_at=datetime(2026, 1, 1, tzinfo=UTC))
VIDEOS = [
    video(1, "2024-01-01T10:00:00", "First\nwalk"),
    video(2, "2024-02-01T10:00:00"),
    video(3, "2024-03-01T10:00:00"),
    video(4, "2025-01-01T10:00:00"),
]


# --- the model --------------------------------------------------------------------------------


def numbers(show: Any) -> list[tuple[int, int, UUID]]:
    return [(e.season, e.number, e.asset_id) for e in show.episodes]


def test_title_and_plot_edits_and_their_reset() -> None:
    edits = {asset_id(1): EpisodeEdit(title="Our walk", plot="")}
    episode = build_show(ALBUM_ROW, VIDEOS, OPTIONS, edits).episodes[0]
    assert (episode.title, episode.plot) == ("Our walk", "")
    assert (episode.auto_title, episode.auto_plot) == ("First", "walk")
    plain = build_show(ALBUM_ROW, VIDEOS, OPTIONS).episodes[0]
    assert (plain.title, plain.plot) == ("First", "walk")


def test_hidden_episode_leaves_no_gap_in_the_numbers() -> None:
    show = build_show(ALBUM_ROW, VIDEOS, OPTIONS, {asset_id(2): EpisodeEdit(hidden=True)})
    assert numbers(show) == [(2024, 1, asset_id(1)), (2024, 2, asset_id(3)), (2025, 1, asset_id(4))]
    assert [e.asset_id for e in show.hidden] == [asset_id(2)]


def test_moving_an_episode_changes_the_order_but_not_the_season() -> None:
    # The March video moved before the January one; the 2025 video moved "into" 2024 by its time.
    edits = {
        asset_id(3): EpisodeEdit(sort_at=datetime(2023, 12, 31, tzinfo=UTC)),
        asset_id(4): EpisodeEdit(sort_at=datetime(2024, 1, 15, tzinfo=UTC)),
    }
    show = build_show(ALBUM_ROW, VIDEOS, OPTIONS, edits)
    assert numbers(show) == [
        (2024, 1, asset_id(3)),
        (2024, 2, asset_id(1)),
        (2024, 3, asset_id(2)),
        (2025, 1, asset_id(4)),
    ]
    # File names stay as they were: watched marks survive a move.
    assert show.episodes[0].file_stem.startswith("20240301-100000")


def test_show_title_edit() -> None:
    show = build_show(ALBUM_ROW, VIDEOS, OPTIONS, show_edit=ShowEdit(title="Our walks"))
    assert (show.title, show.sort_title, show.album_name) == ("◈ Our walks", "Our walks", "Family")


def test_a_hidden_show_does_not_count_as_a_mass_removal() -> None:
    entries = [
        Entry(PurePosixPath(f"s/v{n}.mp4"), FileKind.LINK, ALBUM, link_target=PurePosixPath("/x"))
        for n in range(30)
    ]
    assert make_plan([], entries).is_mass_removal
    assert not make_plan([], entries, removed_on_purpose={ALBUM}).is_mass_removal


# --- the API ----------------------------------------------------------------------------------


class World:
    """Signing in from test_auth, albums and videos from FakeImmich."""

    def __init__(self) -> None:
        self.auth = Immich()
        self.library = FakeImmich()
        self.album = self.library.add_album(1, "Family")
        for n, when in (
            (1, "2024-01-01T10:00:00"),
            (2, "2024-02-01T10:00:00"),
            (3, "2024-03-01T10:00:00"),
        ):
            self.library.add_video(self.album, n, when, description="First\nwalk" if n == 1 else "")

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        if path.startswith(("/api/albums", "/api/search", "/api/assets/")):
            return self.library.handler(request)
        return self.auth.handler(request)


@pytest.fixture
def world() -> World:
    return World()


@pytest.fixture
def client(empty_database: str, world: World) -> Iterator[TestClient]:
    settings = Settings(
        _env_file=None,
        immich_url="http://immich.test",
        immich_api_key=APP_KEY,
        database_url=empty_database,
        secret_key=SECRET,
        path_map="/data=/mnt/immich",
    )
    app = create_app(
        settings, run_scheduler=False, immich_transport=httpx2.MockTransport(world.handler)
    )
    with TestClient(app) as test_client:
        response = test_client.post(
            "/api/auth/login", json={"email": "jellyfin@lab.test", "password": "pass-jf"}
        )
        assert response.status_code == 200
        yield test_client


def episodes(client: TestClient, album: UUID) -> list[dict[str, Any]]:
    response = client.get(f"/api/shows/{album}")
    assert response.status_code == 200, response.text
    return list(response.json()["episode_list"])


def test_shows_need_sign_in(empty_database: str, world: World) -> None:
    settings = Settings(
        _env_file=None,
        immich_url="http://i.test",
        immich_api_key=APP_KEY,
        database_url=empty_database,
        secret_key=SECRET,
    )
    app = create_app(
        settings, run_scheduler=False, immich_transport=httpx2.MockTransport(world.handler)
    )
    with TestClient(app) as anonymous:
        assert anonymous.get("/api/shows").status_code == 401


def test_list_and_rename_a_show(client: TestClient, world: World) -> None:
    shows = client.get("/api/shows").json()
    assert [(s["title"], s["title_edited"], s["season_mode"]) for s in shows] == [
        ("Family", False, "year")
    ]
    response = client.patch(f"/api/shows/{world.album}", json={"title": "  Our walks "})
    assert response.json()["title"] == "Our walks" and response.json()["title_edited"]
    assert client.app.state.status.wake.is_set()  # type: ignore[attr-defined]
    client.patch(f"/api/shows/{world.album}", json={"title": None, "season_mode": "single"})
    show = client.get("/api/shows").json()[0]
    assert (show["title"], show["title_edited"], show["season_mode"]) == ("Family", False, "single")
    assert client.get(f"/api/shows/{album_id(99)}").status_code == 404


def test_edit_hide_and_reset_an_episode(client: TestClient, world: World) -> None:
    first = asset_id(1)
    client.patch(f"/api/shows/{world.album}/episodes/{first}", json={"title": "Our walk"})
    item = episodes(client, world.album)[0]
    assert (item["title"], item["auto_title"], item["title_edited"]) == ("Our walk", "First", True)

    client.patch(f"/api/shows/{world.album}/episodes/{asset_id(2)}", json={"hidden": True})
    listed = episodes(client, world.album)
    assert [(e["number"], e["hidden"]) for e in listed] == [(1, False), (2, False), (0, True)]

    client.patch(f"/api/shows/{world.album}/episodes/{first}", json={"title": None})
    assert episodes(client, world.album)[0]["title"] == "First"


def test_move_an_episode(client: TestClient, world: World) -> None:
    base = f"/api/shows/{world.album}/episodes"
    response = client.post(f"{base}/{asset_id(3)}/move", json={"before": str(asset_id(1))})
    assert response.status_code == 200, response.text
    order = [e["asset_id"] for e in episodes(client, world.album)]
    assert order == [str(asset_id(3)), str(asset_id(1)), str(asset_id(2))]

    client.post(f"{base}/{asset_id(1)}/move", json={"after": str(asset_id(2))})
    order = [e["asset_id"] for e in episodes(client, world.album)]
    assert order == [str(asset_id(3)), str(asset_id(2)), str(asset_id(1))]

    # Between two neighbours.
    client.post(
        f"{base}/{asset_id(1)}/move", json={"after": str(asset_id(3)), "before": str(asset_id(2))}
    )
    listed = episodes(client, world.album)
    assert [e["asset_id"] for e in listed] == [str(asset_id(3)), str(asset_id(1)), str(asset_id(2))]
    assert listed[0]["moved"]

    # Back to the order of filming.
    for n in (1, 3):
        client.patch(f"{base}/{asset_id(n)}", json={"sort_at": None})
    order = [e["asset_id"] for e in episodes(client, world.album)]
    assert order == [str(asset_id(1)), str(asset_id(2)), str(asset_id(3))]
    assert client.post(f"{base}/{asset_id(1)}/move", json={}).status_code == 400


def test_thumbnail_proxy(client: TestClient) -> None:
    response = client.get(f"/api/thumbnails/{asset_id(1)}")
    assert response.status_code == 200
    assert response.content.startswith(b"JPEG")
    assert "private" in response.headers["cache-control"]


# --- a whole sync -----------------------------------------------------------------------------


@pytest.mark.anyio
@pytest.mark.skipif(os.name == "nt", reason="symbolic links need Linux")
async def test_hiding_a_big_show_removes_it_without_being_held(
    session: AsyncSession, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    out.mkdir()
    library = FakeImmich()
    album = library.add_album(1, "Big")
    for n in range(1, 31):
        library.add_video(album, n, f"2024-01-{n:02d}T10:00:00")

    async def sync() -> SyncReport:
        async with library.client() as client:
            return await run_sync(
                immich=client,
                registry=Registry(session),
                executor=Executor(out, [PurePosixPath("/mnt/immich")]),
                target=JellyfinLayout(),
                options=OPTIONS,
            )

    await sync()
    assert len(list(out.rglob("*.mp4"))) == 30

    row = (await Registry(session).shows())[album]
    row.hidden = True
    await session.commit()
    report = await sync()
    assert report.ok and not report.held
    assert list(out.rglob("*.mp4")) == []

    row.hidden = False
    await session.commit()
    await sync()
    assert len(list(out.rglob("*.mp4"))) == 30
