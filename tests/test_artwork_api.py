# SPDX-License-Identifier: AGPL-3.0-or-later
"""Artwork on the page: styles switched on and off, the pictures of a show, a look at other
pictures, and the choices kept for the next pass."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

import pytest
import test_edits
from fastapi.testclient import TestClient
from test_artwork_sync import fake_look
from test_edits import World

from showrunner.api import artwork as artwork_api
from showrunner.store.db import make_engine, make_session_factory
from showrunner.store.registry import Registry

# The signed-in page and its Immich, from the tests of the edits.
client = test_edits.client
world = test_edits.world


def test_styles_can_be_switched_off_but_not_all(client: TestClient) -> None:
    styles = client.get("/api/styles").json()
    ids = [s["id"] for s in styles]
    assert len(ids) == 9 and all(s["enabled"] for s in styles)
    assert next(s for s in styles if s["id"] == "mosaic")["names"]["ru"] == "Мозаика"
    for style_id in ids[:-1]:
        assert client.patch(f"/api/styles/{style_id}", json={"enabled": False}).status_code == 200
    last = client.patch(f"/api/styles/{ids[-1]}", json={"enabled": False})
    assert last.status_code == 400 and last.json()["code"] == "style_last"
    enabled = [s["id"] for s in client.get("/api/styles").json() if s["enabled"]]
    assert enabled == [ids[-1]]
    assert client.patch("/api/styles/nope", json={"enabled": True}).status_code == 404


def test_a_choice_is_kept(client: TestClient, world: World) -> None:
    url = f"/api/shows/{world.album}/artwork"
    first = client.get(url).json()
    assert first == {
        "style_id": None,
        "seed": 0,
        "use_cover": False,
        "slot_seeds": {},
        "pictures": [],
        "waiting": 0,
        "syncing": False,
    }
    choice = {
        "style_id": "film",
        "seed": 42,
        "use_cover": True,
        "slot_seeds": {"season_poster:2024": 5},
    }
    assert client.put(url, json=choice).status_code == 200
    kept = client.get(url).json()
    assert {k: kept[k] for k in choice} == choice
    assert kept["syncing"] is True, "the change asks for a pass"
    assert client.put(url, json={**choice, "style_id": "nope"}).status_code == 404
    bad = client.put(url, json={**choice, "slot_seeds": {"nope": 1}})
    assert bad.status_code == 400 and bad.json()["code"] == "artwork_slot"


def database[T](url: str, work: Callable[[Registry], Awaitable[T]]) -> T:
    """Run `work` on the database of the app, as the passes would."""

    async def run() -> T:
        engine = make_engine(url)
        try:
            async with make_session_factory(engine)() as session:
                registry = Registry(session)
                result = await work(registry)
                await registry.commit()
                return result
        finally:
            await engine.dispose()

    return asyncio.run(run())


def test_pictures_are_pinned_as_drawn(
    client: TestClient, world: World, empty_database: str
) -> None:
    job = {"kind": "series_poster", "season": None, "style_id": "film"}

    async def drawn(registry: Registry) -> None:
        await registry.add_show(world.album, "Family")
        await registry.save_artwork(
            world.album,
            "film",
            drawn_jobs={"series_poster": job, "fanart": {**job, "kind": "fanart"}},
        )

    async def pinned(registry: Registry) -> dict[str, Any]:
        return dict((await registry.artworks())[world.album].pinned_jobs)

    database(empty_database, drawn)
    url = f"/api/shows/{world.album}/artwork/pins"
    one = client.put(url, json={"slots": ["series_poster", "logo"], "pinned": True})
    assert one.json() == {"pinned": ["series_poster"]}, "only what is drawn is pinned"
    every = client.put(url, json={"pinned": True})
    assert every.json() == {"pinned": ["fanart", "series_poster"]}
    assert database(empty_database, pinned)["series_poster"] == job
    pictures = client.get(f"/api/shows/{world.album}/artwork").json()["pictures"]
    assert pictures == [], "nothing written yet: no pictures to show"
    assert client.put(url, json={"slots": ["fanart"], "pinned": False}).json() == {
        "pinned": ["series_poster"]
    }
    assert client.put(url, json={"pinned": False}).json() == {"pinned": []}


def test_no_look_without_frames(client: TestClient, world: World) -> None:
    response = client.post(f"/api/shows/{world.album}/artwork/preview", json={"change": "style"})
    assert response.status_code == 409 and response.json()["code"] == "artwork_not_ready"


@pytest.fixture
def drawn(monkeypatch: pytest.MonkeyPatch) -> list[list[Any]]:
    """Every video has made-up frames; drawing gives tiny PNGs and lists the jobs drawn."""
    calls: list[list[Any]] = []

    def looks_of(show: Any, rows: Any) -> tuple[dict[UUID, list[Any]], int]:
        return {
            e.asset_id: [fake_look(e.asset_id, t) for t in (1.0, 2.0)] for e in show.episodes
        }, 0

    async def draw_preview(jobs: list[Any], source: Any) -> list[bytes]:
        calls.append(jobs)
        return [b"\x89PNG small" for _ in jobs]

    monkeypatch.setattr(artwork_api, "looks_of", looks_of)
    monkeypatch.setattr(artwork_api, "draw_preview", draw_preview)
    return calls


def test_other_style_other_frames_and_the_cover(
    client: TestClient,
    world: World,
    drawn: list[list[Any]],
) -> None:
    url = f"/api/shows/{world.album}/artwork/preview"
    first = client.post(url, json={"change": "style"}).json()
    assert set(first["pictures"]) == {"series_poster", "landscape", "fanart"}
    assert first["pictures"]["fanart"].startswith("data:image/png;base64,")
    seen = [first["choice"]["style_id"]]
    for _ in range(7):
        more = client.post(
            url, json={"change": "style", "current": first["choice"], "seen_styles": seen}
        ).json()
        assert more["choice"]["style_id"] not in seen, "another style while there are others"
        seen.append(more["choice"]["style_id"])

    chosen = client.post(url, json={"change": "style", "style_id": "board"}).json()
    assert chosen["choice"]["style_id"] == "board", "a style chosen by name"
    nope = client.post(url, json={"change": "style", "style_id": "nope"})
    assert nope.status_code == 404

    frames = client.post(url, json={"change": "frames", "current": first["choice"]}).json()
    assert frames["choice"]["style_id"] == first["choice"]["style_id"]
    assert frames["choice"]["seed"] != first["choice"]["seed"]

    cover = client.post(url, json={"change": "cover", "current": first["choice"]}).json()
    assert cover["choice"]["use_cover"] is True
    assert set(cover["pictures"]) == {"landscape", "fanart"}, "the poster is the cover"
    assert [j.kind.value for j in drawn[-1]] == ["landscape", "fanart"]


def test_other_frames_for_one_picture(
    client: TestClient,
    world: World,
    drawn: list[list[Any]],
) -> None:
    url = f"/api/shows/{world.album}/artwork/preview"
    first = client.post(url, json={"change": "drawn"}).json()
    one = client.post(
        url, json={"change": "frames", "slot": "fanart", "current": first["choice"]}
    ).json()
    assert set(one["pictures"]) == {"fanart"}, "only that picture"
    assert one["choice"]["seed"] == first["choice"]["seed"]
    assert set(one["choice"]["slot_seeds"]) == {"fanart"}
    every = client.post(url, json={"change": "frames", "current": one["choice"]}).json()
    assert every["choice"]["slot_seeds"] == {}, "other frames for all of them"
    bad = client.post(url, json={"change": "frames", "slot": "season_poster:x"})
    assert bad.status_code == 400 and bad.json()["code"] == "artwork_slot"


def test_a_switched_off_style_is_not_offered(
    client: TestClient,
    world: World,
    drawn: list[list[Any]],
) -> None:
    for style_id in ("mosaic", "film", "afisha", "watercolor", "board", "diamonds", "diagonal"):
        client.patch(f"/api/styles/{style_id}", json={"enabled": False})
    url = f"/api/shows/{world.album}/artwork/preview"
    offered = {
        client.post(url, json={"change": "style"}).json()["choice"]["style_id"] for _ in range(6)
    }
    assert offered <= {"polaroid", "editorial"}
