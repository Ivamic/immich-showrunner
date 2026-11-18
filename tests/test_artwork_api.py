# SPDX-License-Identifier: AGPL-3.0-or-later
"""Artwork on the page: styles switched on and off, the pictures of a show, a look at other
pictures, and the choices kept for the next pass."""

from typing import Any
from uuid import UUID

import pytest
import test_edits
from fastapi.testclient import TestClient
from test_artwork_sync import fake_look
from test_edits import World

from showrunner.api import artwork as artwork_api

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


def test_a_choice_and_a_freeze_are_kept(client: TestClient, world: World) -> None:
    url = f"/api/shows/{world.album}/artwork"
    first = client.get(url).json()
    assert first == {
        "style_id": None,
        "seed": 0,
        "use_cover": False,
        "frozen": "none",
        "pictures": [],
    }
    choice = {"style_id": "film", "seed": 42, "use_cover": True}
    assert client.put(url, json=choice).status_code == 200
    assert client.put(f"{url}/frozen", json={"frozen": "all"}).status_code == 200
    kept = client.get(url).json()
    assert (kept["style_id"], kept["seed"], kept["use_cover"], kept["frozen"]) == (
        "film",
        42,
        True,
        "all",
    )
    assert client.put(url, json={**choice, "style_id": "nope"}).status_code == 404


def test_no_look_without_frames(client: TestClient, world: World) -> None:
    response = client.post(f"/api/shows/{world.album}/artwork/preview", json={"change": "style"})
    assert response.status_code == 409 and response.json()["code"] == "artwork_not_ready"


@pytest.fixture
def drawn(monkeypatch: pytest.MonkeyPatch) -> list[list[Any]]:
    """Every video has made-up frames; drawing gives tiny PNGs and lists the jobs drawn."""
    calls: list[list[Any]] = []

    def looks_of(show: Any, rows: Any) -> tuple[dict[UUID, list[Any]], bool]:
        return {
            e.asset_id: [fake_look(e.asset_id, t) for t in (1.0, 2.0)] for e in show.episodes
        }, False

    def draw_small(jobs: list[Any], styles: Any, source: Any) -> list[bytes]:
        calls.append(jobs)
        return [b"\x89PNG small" for _ in jobs]

    monkeypatch.setattr(artwork_api, "looks_of", looks_of)
    monkeypatch.setattr(artwork_api, "draw_small", draw_small)
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

    frames = client.post(url, json={"change": "frames", "current": first["choice"]}).json()
    assert frames["choice"]["style_id"] == first["choice"]["style_id"]
    assert frames["choice"]["seed"] != first["choice"]["seed"]

    cover = client.post(url, json={"change": "cover", "current": first["choice"]}).json()
    assert cover["choice"]["use_cover"] is True
    assert set(cover["pictures"]) == {"landscape", "fanart"}, "the poster is the cover"
    assert [j.kind.value for j in drawn[-1]] == ["landscape", "fanart"]


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
