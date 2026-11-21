# SPDX-License-Identifier: AGPL-3.0-or-later
"""Slideshows on the page: the settings, the choices for an album, the state of its slideshows
and a look at one drawn; the music of the set and the user's own pieces, added through the page
and refused with the reason when they are no music for slideshows."""

import asyncio
import hashlib
import json
import os
import time
from collections.abc import Iterator
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import UUID

import httpx2
import pytest
import yaml
from fastapi.testclient import TestClient
from test_edits import World
from test_slideshow_music import piece, write

from showrunner.api import slideshow as slideshow_api
from showrunner.app import create_app
from showrunner.config import Settings
from showrunner.model.show import Special
from showrunner.store.db import make_engine, make_session_factory
from showrunner.store.registry import Registry
from showrunner.targets.base import SLIDESHOWS, DesiredFile, FileKind, VideoSource
from showrunner.targets.specials import store_file
from test_auth import APP_KEY, SECRET


class InProcess:
    """The worker, in this process."""

    async def run(self, task: Any, *args: Any) -> Any:
        return task(*args)


@pytest.fixture
def world() -> World:
    return World()


@pytest.fixture
def data(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture
def client(
    empty_database: str, world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    monkeypatch.setattr(slideshow_api, "render_worker", InProcess)
    (tmp_path / "store").mkdir()
    settings = Settings(
        _env_file=None,
        immich_url="http://immich.test",
        immich_api_key=APP_KEY,
        database_url=empty_database,
        secret_key=SECRET,
        path_map="/data=/mnt/immich",
        data_dir=tmp_path / "data",
        slideshow_dir=tmp_path / "store",
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


def in_db(database: str, work: Any) -> Any:
    async def run() -> Any:
        engine = make_engine(database)
        async with make_session_factory(engine)() as session:
            result = await work(Registry(session))
            await session.commit()
        await engine.dispose()
        return result

    return asyncio.run(run())


# --- settings and albums ----------------------------------------------------------------------


def test_slideshows_are_switched_on_on_the_page(client: TestClient) -> None:
    got = client.get("/api/slideshow/settings").json()
    assert got == {"enabled": False, "credits": True, "folder": True, "data": True}
    put = client.put("/api/slideshow/settings", json={"enabled": True})
    assert put.json()["enabled"] is True and put.json()["credits"] is True
    put = client.put("/api/slideshow/settings", json={"credits": False})
    assert put.json() == {"enabled": True, "credits": False, "folder": True, "data": True}


def plan_of(database: str, album: UUID, version: str = "v1") -> None:
    planned = [
        {
            "year": 2024,
            "part": 0,
            "title": "Photos 2024",
            "seconds": 100.0,
            "photos": 23,
            "left_out": 5,
            "music": ["“Piece” by Someone, CC BY 4.0"],
            "version": version,
        }
    ]

    async def work(registry: Registry) -> None:
        if album not in await registry.shows():
            await registry.add_show(album, "Family")
        await registry.save_album_slideshow(album, auto_mood="bright", planned=planned)

    in_db(database, work)


def draw(database: str, store: Path, album: UUID, version: str, content: bytes) -> None:
    folder = "Family [imm-00000001]"
    relative = store_file(folder, 2024, 0)
    (store / relative).parent.mkdir(parents=True, exist_ok=True)
    (store / relative).write_bytes(content)
    special = Special(2024, 0, 1, 1, "Photos 2024", "", date(2024, 12, 31), None, version, None)
    file = DesiredFile(
        path=PurePosixPath(relative),
        kind=FileKind.VIDEO,
        album_id=album,
        video=VideoSource(album, special),
        drawn_hash=hashlib.sha256(content).hexdigest(),
    )

    async def work(registry: Registry) -> None:
        await registry.record(file, SLIDESHOWS)

    in_db(database, work)


def test_the_slideshows_of_an_album_their_state_and_a_look(
    client: TestClient, world: World, empty_database: str, tmp_path: Path
) -> None:
    album = world.album
    empty = client.get(f"/api/shows/{album}/slideshow").json()
    assert empty == {"enabled": None, "mood": None, "auto_mood": None, "slideshows": []}
    plan_of(empty_database, album)
    (waiting,) = client.get(f"/api/shows/{album}/slideshow").json()["slideshows"]
    assert waiting["state"] == "waiting" and waiting["photos"] == 23
    assert client.get(f"/api/shows/{album}/slideshow/video?year=2024&part=0").status_code == 404

    draw(empty_database, tmp_path / "store", album, "v0", b"an older slideshow")
    (older,) = client.get(f"/api/shows/{album}/slideshow").json()["slideshows"]
    assert older["state"] == "older", "the one before is shown while this one waits"
    draw(empty_database, tmp_path / "store", album, "v1", b"the slideshow")
    (drawn,) = client.get(f"/api/shows/{album}/slideshow").json()["slideshows"]
    assert drawn["state"] == "drawn"
    look = client.get(f"/api/shows/{album}/slideshow/video?year=2024&part=0")
    assert look.status_code == 200 and look.content == b"the slideshow"
    assert look.headers["content-type"] == "video/mp4"


def test_a_slideshow_is_saved_under_the_name_of_the_show(
    client: TestClient, world: World, empty_database: str, tmp_path: Path
) -> None:
    album = world.album
    plan_of(empty_database, album)
    draw(empty_database, tmp_path / "store", album, "v1", b"the slideshow")
    saved = client.get(f"/api/shows/{album}/slideshow/video?year=2024&part=0&download=1")
    assert saved.status_code == 200 and saved.content == b"the slideshow"
    assert "Family%20-%20Photos%202024.mp4" in saved.headers["content-disposition"]
    assert saved.headers["content-disposition"].startswith("attachment")


def test_the_slideshows_drawn_before_are_listed_and_saved_from_the_trash(
    client: TestClient, world: World, empty_database: str, tmp_path: Path
) -> None:
    album = world.album
    plan_of(empty_database, album)
    assert client.get(f"/api/shows/{album}/slideshow/trash").json() == []

    async def folder_of(registry: Registry) -> str:
        return (await registry.shows())[album].folder_name

    trash = tmp_path / "store" / ".trash" / in_db(empty_database, folder_of)
    trash.mkdir(parents=True)
    (trash / "Photos 2024 (until 20261101-120000).mp4").write_bytes(b"before")
    (listed,) = client.get(f"/api/shows/{album}/slideshow/trash").json()
    assert listed["name"] == "Photos 2024 (until 20261101-120000).mp4" and listed["size"] == 6
    url = f"/api/shows/{album}/slideshow/trash/file"
    got = client.get(url, params={"name": listed["name"]})
    assert got.status_code == 200 and got.content == b"before"
    for name in ("../x.mp4", ".hidden", "missing.mp4"):
        assert client.get(url, params={"name": name}).status_code == 404


def test_what_became_of_each_photo_is_shown_for_a_slideshow(
    client: TestClient, world: World, tmp_path: Path
) -> None:
    album = world.album
    url = f"/api/shows/{album}/slideshow/plan?year=2024&part=0"
    assert client.get(url).status_code == 404
    photos = [
        {
            "id": "00000000-0000-0000-0000-000000000001",
            "taken": "2024-07-01T09:00:00",
            "scene": 0,
            "group": "00000000-0000-0000-0000-000000000001",
            "fate": "shown",
            "score": 0.8,
        },
        {
            "id": "00000000-0000-0000-0000-000000000002",
            "taken": "2024-07-01T09:00:05",
            "scene": 0,
            "group": "00000000-0000-0000-0000-000000000001",
            "fate": "series",
            "score": 0.6,
        },
    ]
    kept = {"slideshows": [{"year": 2024, "part": 0, "title": "Photos 2024", "photos": photos}]}
    path = tmp_path / "data" / "slideshow-plans" / f"{album}.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(kept), encoding="utf-8")
    got = client.get(url).json()
    assert got["title"] == "Photos 2024"
    assert [p["fate"] for p in got["photos"]] == ["shown", "series"]
    assert client.get(f"/api/shows/{album}/slideshow/plan?year=2023&part=0").status_code == 404


def test_the_drawing_now_is_shown_with_how_far_it_is(client: TestClient, tmp_path: Path) -> None:
    assert client.get("/api/slideshow/progress").json() is None
    work = tmp_path / "data" / "slideshows"
    work.mkdir(parents=True)
    note = {
        "album_id": None,
        "show": "Family",
        "title": "Photos 2024",
        "started": "2026-11-21T10:00:00+00:00",
        "queue": 2,
    }
    (work / "progress.json").write_text(json.dumps(note), encoding="utf-8")
    fetching = client.get("/api/slideshow/progress").json()
    assert fetching["title"] == "Photos 2024" and fetching["percent"] is None
    assert fetching["queue"] == 2
    (work / "frames.json").write_text(json.dumps({"frames": 450, "total": 1800}), encoding="utf-8")
    assert client.get("/api/slideshow/progress").json()["percent"] == 25
    old = time.time() - 3600
    for name in ("progress.json", "frames.json"):
        os.utime(work / name, (old, old))
    assert client.get("/api/slideshow/progress").json() is None, "left over from a stopped pass"


def test_a_choice_for_an_album_asks_for_a_pass(client: TestClient, world: World) -> None:
    album = world.album
    state = client.app.state.status  # type: ignore[attr-defined]
    state.full_next = False
    got = client.put(f"/api/shows/{album}/slideshow", json={"mood": "wistful"}).json()
    assert got["mood"] == "wistful" and got["enabled"] is None
    assert state.full_next
    got = client.put(f"/api/shows/{album}/slideshow", json={"enabled": False}).json()
    assert got["enabled"] is False and got["mood"] == "wistful", "the rest stays"
    got = client.put(f"/api/shows/{album}/slideshow", json={"enabled": None, "mood": None}).json()
    assert (got["enabled"], got["mood"]) == (None, None)
    assert client.put(f"/api/shows/{album}/slideshow", json={"mood": "sad"}).status_code == 422


def test_other_music_takes_another_order_of_the_pieces(
    client: TestClient, world: World, empty_database: str
) -> None:
    album = world.album
    for _ in range(2):
        client.put(f"/api/shows/{album}/slideshow", json={"other_music": True})

    async def work(registry: Registry) -> int:
        return (await registry.album_slideshows())[album].music_seed

    assert in_db(empty_database, work) == 2


# --- music ------------------------------------------------------------------------------------


def song(tmp_path: Path, seconds: float = 40) -> bytes:
    return write(tmp_path / f"song-{seconds}.wav", piece(seconds=seconds, bpm=110)).read_bytes()


def test_own_music_is_added_looked_at_described_and_removed(
    client: TestClient, tmp_path: Path, data: Path
) -> None:
    added = client.put("/api/music/own/Our song.wav", content=song(tmp_path))
    assert added.status_code == 200, added.text
    track = added.json()
    assert track["kind"] == "own" and track["seconds"] > 30 and track["error"] is None
    assert track["title"] == "Our song" and track["mood"]
    assert (data / "music" / "own" / "Our song.wav").exists()

    listed = client.get("/api/music").json()
    assert any(t["id"] == track["id"] for t in listed)
    assert any(t["kind"] == "set" and not t["present"] for t in listed), "the set, not there yet"

    patched = client.patch(
        f"/api/music/{track['id']}",
        json={"title": "Song of the summer", "author": "Uncle Bob", "mood": "upbeat"},
    ).json()
    assert (patched["title"], patched["author"], patched["mood"]) == (
        "Song of the summer",
        "Uncle Bob",
        "upbeat",
    )
    side = yaml.safe_load((data / "music" / "own" / "Our song.yaml").read_text(encoding="utf-8"))
    assert side == {"title": "Song of the summer", "author": "Uncle Bob", "mood": "upbeat"}
    cleared = client.patch(f"/api/music/{patched['id']}", json={"author": ""}).json()
    assert cleared["author"] == ""

    heard = client.get(f"/api/music/file/{cleared['id']}")
    assert heard.status_code == 200 and heard.headers["content-type"] == "audio/wav"

    assert client.delete(f"/api/music/{cleared['id']}").json() == {"removed": True}
    assert not (data / "music" / "own" / "Our song.wav").exists()


def test_what_is_no_music_is_refused_with_the_reason(
    client: TestClient, tmp_path: Path, data: Path
) -> None:
    short = client.put("/api/music/own/short.wav", content=song(tmp_path, 10))
    assert short.status_code == 400
    assert (
        short.json()["code"] == "music_not_usable" and "lasts" in short.json()["params"]["reason"]
    )
    assert not list((data / "music" / "own").iterdir()), "not kept"
    wrong = client.put("/api/music/own/notes.txt", content=b"hello")
    assert wrong.json()["code"] == "music_file_type"
    client.put("/api/music/own/a.wav", content=song(tmp_path))
    again = client.put("/api/music/own/a.wav", content=song(tmp_path))
    assert again.status_code == 409


def test_a_piece_of_the_set_is_switched_off_but_not_changed(client: TestClient) -> None:
    first = next(t for t in client.get("/api/music").json() if t["kind"] == "set")
    off = client.patch(f"/api/music/{first['id']}", json={"enabled": False}).json()
    assert off["enabled"] is False
    assert client.patch(f"/api/music/{first['id']}", json={"title": "x"}).status_code == 400
    assert client.delete(f"/api/music/{first['id']}").status_code == 400
