# SPDX-License-Identifier: AGPL-3.0-or-later
"""Telling Kodi over JSON-RPC: which calls, in which order, and what happens when it is off."""

import json
from typing import Any
from uuid import UUID

import httpx2
import pytest

from showrunner.targets.kodi.client import (
    KodiAuthError,
    KodiClient,
    KodiError,
    KodiUnreachableError,
    folder_path,
    tell_kodi,
)

pytestmark = pytest.mark.anyio

A1 = UUID("97769e09-f6ec-4d0b-86d0-3237df31f35b")
A2 = UUID("23949b13-40de-42fc-b91b-dfb7659ddf88")
A3 = UUID("00000003-0000-4000-8000-000000000000")
OUTPUT = "smb://server/bridge/kodi"


class FakeKodi:
    def __init__(self, *, reachable_folder: bool = True, missing: str = "") -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.reachable_folder = reachable_folder
        self.missing = missing
        self.auth: str | None = None

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        self.auth = request.headers.get("authorization")
        body = json.loads(request.content)
        method, params = body["method"], body.get("params", {})
        self.calls.append((method, params))
        result: Any = "OK"
        if method == "VideoLibrary.GetTVShows":
            result = {
                "tvshows": [
                    {"tvshowid": 11, "uniqueid": {"immich": str(A1)}},
                    {"tvshowid": 12, "uniqueid": {"immich": str(A2)}},
                    {"tvshowid": 13, "uniqueid": {"tvdb": "123"}},
                    {"tvshowid": 14, "uniqueid": {"immich": "not-an-id"}},
                ]
            }
        elif method == "Files.GetDirectory" and (
            not self.reachable_folder or (self.missing and self.missing in params["directory"])
        ):
            return httpx2.Response(
                200, json={"id": body["id"], "jsonrpc": "2.0", "error": {"message": "Invalid"}}
            )
        elif method == "Application.GetProperties":
            result = {"version": {"major": 21, "minor": 3}}
        return httpx2.Response(200, json={"id": body["id"], "jsonrpc": "2.0", "result": result})

    def client(self) -> KodiClient:
        return KodiClient(
            "http://kodi.test:8080/", "kodi", "secret", transport=httpx2.MockTransport(self.handler)
        )

    def methods(self) -> list[str]:
        return [method for method, _ in self.calls]


def test_folder_paths() -> None:
    assert folder_path("smb://server/bridge/kodi/", "Summer") == "smb://server/bridge/kodi/Summer/"
    assert folder_path("nfs://n/kodi") == "nfs://n/kodi/"
    assert folder_path("D:\\media\\kodi", "Summer") == "D:\\media\\kodi\\Summer\\"


async def test_client_basics() -> None:
    kodi = FakeKodi()
    async with kodi.client() as client:
        assert await client.version() == "21.3"
        assert await client.shows() == {A1: 11, A2: 12}
    assert kodi.auth == "Basic a29kaTpzZWNyZXQ="


async def test_nothing_to_tell_calls_nothing() -> None:
    kodi = FakeKodi()
    async with kodi.client() as client:
        assert await tell_kodi(client, OUTPUT, {}, set()) == []
    assert kodi.calls == []


async def test_changed_shows_are_cleaned_scanned_and_refreshed() -> None:
    kodi = FakeKodi()
    async with kodi.client() as client:
        done = await tell_kodi(client, OUTPUT, {A1: "Summer [imm-97769e09]", A3: "New"}, set())
    assert kodi.methods() == [
        "Files.GetDirectory",
        "VideoLibrary.GetTVShows",
        "Files.GetDirectory",
        "VideoLibrary.Clean",
        "VideoLibrary.Scan",
        "VideoLibrary.RefreshTVShow",
    ]
    assert kodi.calls[2][1]["directory"] == f"{OUTPUT}/Summer [imm-97769e09]/"
    clean, scan, refresh = (params for _, params in kodi.calls[3:])
    # The clean is limited to the folder of the show: Kodi never cleans the rest of the library.
    assert clean["directory"] == f"{OUTPUT}/Summer [imm-97769e09]/"
    assert scan["directory"] == f"{OUTPUT}/"
    assert (refresh["tvshowid"], refresh["refreshepisodes"]) == (11, True)
    assert clean["showdialogs"] is False and scan["showdialogs"] is False
    assert done == [
        "Kodi: scanned the library",
        f"Kodi: refreshed the show of album {A1}",
    ]


async def test_a_gone_show_is_removed() -> None:
    kodi = FakeKodi()
    async with kodi.client() as client:
        done = await tell_kodi(client, OUTPUT, {}, {A2, A3})
    assert kodi.methods() == [
        "Files.GetDirectory",
        "VideoLibrary.GetTVShows",
        "VideoLibrary.RemoveTVShow",
    ]
    assert kodi.calls[2][1] == {"tvshowid": 12}
    assert done == [f"Kodi: removed the show of album {A2}"]


async def test_nothing_is_cleaned_when_kodi_can_not_open_the_folder() -> None:
    kodi = FakeKodi(reachable_folder=False)
    async with kodi.client() as client:
        with pytest.raises(KodiError, match="can not open"):
            await tell_kodi(client, OUTPUT, {A1: "Summer"}, {A2})
    assert kodi.methods() == ["Files.GetDirectory"]


async def test_kodi_off_or_wrong_password() -> None:
    def off(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused")

    async with KodiClient("http://kodi.test", "kodi", "", transport=httpx2.MockTransport(off)) as c:
        with pytest.raises(KodiUnreachableError):
            await c.version()

    def denied(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(401)

    transport = httpx2.MockTransport(denied)
    async with KodiClient("http://kodi.test", "kodi", "x", transport=transport) as c:
        with pytest.raises(KodiAuthError):
            await c.version()


async def test_nothing_is_cleaned_when_kodi_can_not_open_the_folder_of_a_show() -> None:
    kodi = FakeKodi(missing="Summer")
    async with kodi.client() as client:
        with pytest.raises(KodiError, match="Summer"):
            await tell_kodi(client, OUTPUT, {A1: "Summer [imm-97769e09]"}, set())
    assert "VideoLibrary.Clean" not in kodi.methods()
