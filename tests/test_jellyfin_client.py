# SPDX-License-Identifier: AGPL-3.0-or-later
from pathlib import PurePosixPath
from uuid import UUID

import httpx2
import pytest

from showrunner.targets.jellyfin.client import (
    JellyfinAuthError,
    JellyfinClient,
    JellyfinUnreachableError,
    tell_jellyfin,
)

pytestmark = pytest.mark.anyio

A1 = UUID("97769e09-f6ec-4d0b-86d0-3237df31f35b")
A2 = UUID("23949b13-40de-42fc-b91b-dfb7659ddf88")
A3 = UUID("00000003-0000-4000-8000-000000000000")
OUTPUT = PurePosixPath("/media/showrunner")


class FakeJellyfin:
    def __init__(self, *, library_path: str = "/media/showrunner") -> None:
        self.calls: list[str] = []
        self.library_path = library_path
        self.last: httpx2.Request | None = None

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        self.last = request
        path = request.url.path
        self.calls.append(f"{request.method} {path}")
        if path == "/Items":
            return httpx2.Response(
                200,
                json={
                    "Items": [
                        {"Id": "series-1", "ProviderIds": {"immich": str(A1)}},
                        {"Id": "series-2", "ProviderIds": {"Immich": str(A2)}},
                        {"Id": "a-film-show", "ProviderIds": {"Tvdb": "123"}},
                        {"Id": "broken", "ProviderIds": {"immich": "not-an-id"}},
                    ]
                },
            )
        if path == "/Library/VirtualFolders":
            return httpx2.Response(
                200,
                json=[
                    {"Name": "Films", "Locations": ["/media/films"], "ItemId": "lib-films"},
                    {"Name": "Immich", "Locations": [self.library_path], "ItemId": "lib-immich"},
                ],
            )
        if path == "/System/Info":
            return httpx2.Response(200, json={"Version": "12.4.0"})
        return httpx2.Response(204)

    def client(self) -> JellyfinClient:
        return JellyfinClient(
            "http://jellyfin.test/", "secret", transport=httpx2.MockTransport(self.handler)
        )


async def test_auth_header_and_version() -> None:
    fake = FakeJellyfin()
    async with fake.client() as client:
        assert await client.version() == "12.4.0"
    assert fake.last is not None
    assert fake.last.headers["Authorization"] == 'MediaBrowser Token="secret"'


async def test_shows_are_found_by_the_album_id() -> None:
    fake = FakeJellyfin()
    async with fake.client() as client:
        assert await client.shows() == {A1: "series-1", A2: "series-2"}


async def test_refresh_show_replaces_metadata() -> None:
    fake = FakeJellyfin()
    async with fake.client() as client:
        await client.refresh_show("series-1")
    assert fake.last is not None
    assert fake.last.url.path == "/Items/series-1/Refresh"
    params = dict(fake.last.url.params)
    assert params["ReplaceAllMetadata"] == "true"
    assert params["MetadataRefreshMode"] == "FullRefresh"
    assert params["Recursive"] == "true"


async def test_nothing_changed_nothing_asked() -> None:
    fake = FakeJellyfin()
    async with fake.client() as client:
        assert await tell_jellyfin(client, OUTPUT, set(), set()) == []
    assert fake.calls == []


async def test_known_show_is_refreshed_without_a_scan() -> None:
    fake = FakeJellyfin()
    async with fake.client() as client:
        await tell_jellyfin(client, OUTPUT, {A1}, set())
    assert fake.calls == ["GET /Items", "POST /Items/series-1/Refresh"]


async def test_new_show_needs_a_scan_of_its_library() -> None:
    fake = FakeJellyfin()
    async with fake.client() as client:
        await tell_jellyfin(client, OUTPUT, {A1, A3}, set())
    assert fake.calls == [
        "GET /Items",
        "GET /Library/VirtualFolders",
        "POST /Items/lib-immich/Refresh",
        "POST /Items/series-1/Refresh",
    ]


async def test_gone_show_needs_a_scan() -> None:
    fake = FakeJellyfin()
    async with fake.client() as client:
        await tell_jellyfin(client, OUTPUT, set(), {A2})
    assert fake.calls == [
        "GET /Items",
        "GET /Library/VirtualFolders",
        "POST /Items/lib-immich/Refresh",
    ]


async def test_without_a_matching_library_everything_is_scanned() -> None:
    fake = FakeJellyfin(library_path="/somewhere/else")
    async with fake.client() as client:
        done = await tell_jellyfin(client, OUTPUT, {A3}, set())
    assert fake.calls[-1] == "POST /Library/Refresh"
    assert "all libraries" in done[0]


async def test_errors() -> None:
    def rejected(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(401)

    def refused(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused")

    async with JellyfinClient("http://j.test", "k", transport=httpx2.MockTransport(rejected)) as c:
        with pytest.raises(JellyfinAuthError):
            await c.shows()
    async with JellyfinClient("http://j.test", "k", transport=httpx2.MockTransport(refused)) as c:
        with pytest.raises(JellyfinUnreachableError):
            await c.version()
