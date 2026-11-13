# SPDX-License-Identifier: AGPL-3.0-or-later
"""People of the app in Jellyfin: cleaned of what TMDB said about a namesake, locked, with the
face from Immich. People of other libraries stay as they are."""

import base64
import json
from typing import Any
from uuid import UUID

import httpx2
import pytest

from showrunner.immich.client import ImmichClient
from showrunner.targets.jellyfin.client import JellyfinClient
from showrunner.targets.jellyfin.people import cleaned, tend_people

pytestmark = pytest.mark.anyio

ANNA = UUID("8800ba4a-52a0-4f68-944a-6587ea5ff3c2")


class Jellyfin:
    def __init__(self) -> None:
        self.items: dict[str, dict[str, Any]] = {
            "p-anna": {
                "Id": "p-anna",
                "Name": "◈ Anna",
                "LockData": False,
                "ProviderIds": {"Tmdb": "2871785"},
                "ProductionLocations": ["Russia"],
                "Overview": "An actress.",
            },
            "p-done": {"Id": "p-done", "Name": "◈ Done", "LockData": True, "ProviderIds": {}},
            "p-actor": {
                "Id": "p-actor",
                "Name": "Anna",
                "LockData": False,
                "ProviderIds": {"Tmdb": "1"},
            },
            "p-noface": {"Id": "p-noface", "Name": "◈ Nobody", "LockData": False},
        }
        self.images: dict[str, bytes] = {}
        self.calls: list[str] = []

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        self.calls.append(f"{request.method} {path}")
        if path == "/Persons":
            items = [{"Id": i["Id"], "Name": i["Name"]} for i in self.items.values()]
            return httpx2.Response(200, json={"Items": items})
        if path == "/Users":
            return httpx2.Response(
                200,
                json=[
                    {"Id": "viewer", "Policy": {"IsAdministrator": False}},
                    {"Id": "admin", "Policy": {"IsAdministrator": True}},
                ],
            )
        item_id = path.split("/")[2] if path.startswith("/Items/") else ""
        if path.endswith("/Images/Primary"):
            assert request.headers["Content-Type"] == "image/jpeg"
            self.images[item_id] = base64.b64decode(request.content)
            return httpx2.Response(204)
        if request.method == "GET" and item_id:
            assert request.url.params["userId"] == "admin"
            return httpx2.Response(200, json=self.items[item_id])
        if request.method == "POST" and item_id:
            self.items[item_id] = json.loads(request.content)
            return httpx2.Response(204)
        return httpx2.Response(404)

    def client(self) -> JellyfinClient:
        return JellyfinClient("http://j.test", "k", transport=httpx2.MockTransport(self.handler))


def immich(faces: dict[UUID, bytes]) -> ImmichClient:
    def handler(request: httpx2.Request) -> httpx2.Response:
        person = UUID(request.url.path.split("/")[3])
        if person not in faces:
            return httpx2.Response(404, json={"message": "no such person"})
        return httpx2.Response(200, content=faces[person], headers={"content-type": "image/jpeg"})

    return ImmichClient("http://i.test", "k", transport=httpx2.MockTransport(handler))


def test_cleaned_keeps_the_rest_of_the_item() -> None:
    item = {"Id": "x", "Name": "◈ A", "ProviderIds": {"Tmdb": "1", "Imdb": "2"}, "Genres": ["g"]}
    result = cleaned(item)
    assert result["ProviderIds"] == {"Tmdb": "", "Imdb": ""}
    assert result["LockData"] is True
    assert (result["Name"], result["Genres"]) == ("◈ A", ["g"])
    assert result["Overview"] == "" and result["ProductionLocations"] == []
    assert item["ProviderIds"] == {"Tmdb": "1", "Imdb": "2"}  # the original is not changed


async def test_new_people_of_the_app_are_taken_care_of() -> None:
    jellyfin = Jellyfin()
    async with jellyfin.client() as jf, immich({ANNA: b"face of Anna"}) as im:
        notes = await tend_people(jf, im, "◈ ", {"◈ Anna": ANNA, "◈ Nobody": UUID(int=5)})

    anna = jellyfin.items["p-anna"]
    assert anna["LockData"] is True
    assert anna["ProviderIds"] == {"Tmdb": ""}
    assert anna["ProductionLocations"] == [] and anna["Overview"] == ""
    assert jellyfin.images == {"p-anna": b"face of Anna"}
    # Without a face in Immich the person is still cleaned and locked.
    assert jellyfin.items["p-noface"]["LockData"] is True
    assert "p-noface" not in jellyfin.images
    # Already taken care of, and somebody of another library: not touched.
    assert jellyfin.items["p-actor"]["ProviderIds"] == {"Tmdb": "1"}
    assert "POST /Items/p-done" not in jellyfin.calls
    assert sorted(notes) == ["took care of the person ◈ Anna", "took care of the person ◈ Nobody"]


async def test_second_pass_does_nothing() -> None:
    jellyfin = Jellyfin()
    async with jellyfin.client() as jf, immich({ANNA: b"face"}) as im:
        await tend_people(jf, im, "◈ ", {"◈ Anna": ANNA})
        jellyfin.calls.clear()
        assert await tend_people(jf, im, "◈ ", {"◈ Anna": ANNA}) == []
    assert not [c for c in jellyfin.calls if c.startswith("POST")]


async def test_without_a_prefix_nobody_is_touched() -> None:
    jellyfin = Jellyfin()
    async with jellyfin.client() as jf, immich({}) as im:
        assert await tend_people(jf, im, "", {}) == []
        assert await tend_people(jf, im, "  ", {}) == []
    assert jellyfin.calls == []


async def test_a_person_the_app_did_not_write_is_left_alone() -> None:
    jellyfin = Jellyfin()
    async with jellyfin.client() as jf, immich({ANNA: b"face"}) as im:
        notes = await tend_people(jf, im, "◈ ", {"◈ Anna": ANNA})
    assert notes == ["took care of the person ◈ Anna"]
    assert jellyfin.items["p-noface"]["LockData"] is False


async def test_descriptions_reach_new_and_taken_care_of_people() -> None:
    jellyfin = Jellyfin()
    async with jellyfin.client() as jf, immich({ANNA: b"face"}) as im:
        await tend_people(jf, im, "◈ ", {"◈ Anna": ANNA}, {ANNA: "Grandmother."})
        assert jellyfin.items["p-anna"]["Overview"] == "Grandmother."

        # Changed on the page later: written to the person that is already locked.
        notes = await tend_people(jf, im, "◈ ", {"◈ Anna": ANNA}, {ANNA: "Loves apples."})
        assert notes == ["wrote the description of ◈ Anna"]
        assert jellyfin.items["p-anna"]["Overview"] == "Loves apples."
        assert jellyfin.items["p-anna"]["LockData"] is True

        # Unchanged: nothing written.
        jellyfin.calls.clear()
        await tend_people(jf, im, "◈ ", {"◈ Anna": ANNA}, {ANNA: "Loves apples."})
        assert not [c for c in jellyfin.calls if c.startswith("POST")]
