# SPDX-License-Identifier: AGPL-3.0-or-later
"""The client against canned answers shaped like the ones of Immich 3.4."""

import json
from typing import Any
from uuid import UUID

import httpx2
import pytest

from showrunner.immich.client import (
    ImmichAuthError,
    ImmichClient,
    ImmichError,
    ImmichPermissionError,
    ImmichUnreachableError,
    excess_permissions,
    missing_permissions,
)
from showrunner.immich.models import ApiKeyInfo

pytestmark = pytest.mark.anyio

ALBUM_ID = "97769e09-f6ec-4d0b-86d0-3237df31f35b"
OWNER_ID = "7be25f09-c8d5-437a-993a-9cfde9b73b67"
VIEWER_ID = "f7ec234a-1f0d-4bca-9040-28e639a44668"


def album() -> dict[str, Any]:
    return {
        "id": ALBUM_ID,
        "albumName": "Family archive",
        "description": "",
        "albumThumbnailAssetId": "da01ae15-4168-40a5-88eb-196102de3042",
        "assetCount": 2,
        "updatedAt": "2026-11-13T11:44:51.801Z",
        "lastModifiedAssetTimestamp": "2026-11-13T11:44:52.159Z",
        "albumUsers": [
            {"user": {"id": OWNER_ID, "name": "Owner"}, "role": "owner"},
            {"user": {"id": VIEWER_ID, "name": "viewer"}, "role": "viewer"},
        ],
        "somethingNew": "ignored",
    }


def asset(n: int, *, people: list[dict[str, str]] | None = None) -> dict[str, Any]:
    return {
        "id": f"00000000-0000-4000-8000-{n:012d}",
        "type": "VIDEO",
        "ownerId": OWNER_ID,
        "originalPath": f"/data/upload/{OWNER_ID}/aa/bb/file{n}.mp4",
        "originalFileName": f"VID_{n}.mp4",
        "localDateTime": "2024-07-15T14:32:00.000Z",
        "duration": 6000,
        "isTrashed": False,
        "visibility": "timeline",
        "updatedAt": "2026-11-13T11:42:27.793Z",
        "exifInfo": {"description": "First steps\nIn the living room."},
        "people": people or [],
    }


def client(handler: Any) -> ImmichClient:
    return ImmichClient("http://immich.test", "secret", transport=httpx2.MockTransport(handler))


async def test_albums_and_headers() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json=[album()])

    async with client(handler) as immich:
        albums = await immich.albums()

    assert seen[0].url.path == "/api/albums"
    assert seen[0].headers["x-api-key"] == "secret"
    assert albums[0].album_name == "Family archive"
    assert albums[0].owner_id == UUID(OWNER_ID)
    assert albums[0].last_modified_asset_timestamp is not None


async def test_album_videos_follows_pages() -> None:
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        bodies.append(body)
        if body["page"] == 1:
            return httpx2.Response(200, json={"assets": {"items": [asset(1)], "nextPage": "2"}})
        person = {"id": "8800ba4a-52a0-4f68-944a-6587ea5ff3c2", "name": "Anna"}
        return httpx2.Response(
            200, json={"assets": {"items": [asset(2, people=[person])], "nextPage": None}}
        )

    async with client(handler) as immich:
        videos = [video async for video in immich.album_videos(UUID(ALBUM_ID))]

    assert [b["page"] for b in bodies] == [1, 2]
    assert bodies[0]["albumIds"] == [ALBUM_ID]
    assert bodies[0]["type"] == "VIDEO"
    assert bodies[0]["withPeople"] is True
    assert [v.original_file_name for v in videos] == ["VID_1.mp4", "VID_2.mp4"]
    assert videos[0].description.startswith("First steps")
    assert videos[0].local_date_time.hour == 14
    assert videos[1].people[0].name == "Anna"


@pytest.mark.parametrize(
    ("status", "error"),
    [(401, ImmichAuthError), (403, ImmichPermissionError), (500, ImmichError)],
)
async def test_errors(status: int, error: type[Exception]) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(status, json={"message": "Missing required permission: album.read"})

    async with client(handler) as immich:
        with pytest.raises(error) as caught:
            await immich.albums()
    assert caught.value.status == status  # type: ignore[attr-defined]


async def test_unreachable() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused")

    async with client(handler) as immich:
        with pytest.raises(ImmichUnreachableError):
            await immich.server_version()


def key(*permissions: str) -> ApiKeyInfo:
    return ApiKeyInfo(id=UUID(ALBUM_ID), name="k", permissions=list(permissions))


def test_permissions() -> None:
    read_only = key("album.read", "asset.read", "asset.view", "person.read", "user.read")
    assert missing_permissions(read_only) == frozenset()
    assert excess_permissions(read_only) == frozenset()

    assert missing_permissions(key("album.read")) == {
        "asset.read",
        "asset.view",
        "person.read",
        "user.read",
    }
    assert missing_permissions(key("all")) == frozenset()
    assert excess_permissions(key("all")) == {"all"}
    assert excess_permissions(key("album.read", "asset.delete")) == {"asset.delete"}
