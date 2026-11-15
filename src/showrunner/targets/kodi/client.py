# SPDX-License-Identifier: AGPL-3.0-or-later
"""Kodi over JSON-RPC, as far as the app needs it (checked on Kodi 21.3).

A scan adds new files, but Kodi does not read the NFO of a file it already knows, nor notices
a removed one. So after a change the app removes what is gone from the folder of the show,
scans for what is new and refreshes the show, which reads its NFO files again. Watched marks
stay: they belong to the files, and the names of the files never change."""

import base64
from collections.abc import Collection, Mapping
from types import TracebackType
from typing import Any, Self
from uuid import UUID

import httpx2

from showrunner.targets.nfo import UNIQUE_ID_TYPE

DEFAULT_TIMEOUT_S = 30.0


class KodiError(Exception):
    pass


class KodiUnreachableError(KodiError):
    """Kodi did not answer: it is off, asleep, or its web server is not enabled."""


class KodiAuthError(KodiError):
    """Kodi rejected the user name or the password."""


def folder_path(output_path: str, folder_name: str = "") -> str:
    """A folder as Kodi names it, with the separator Kodi uses at the end:
    `smb://server/share/kodi` + `Summer [imm-…]` -> `smb://server/share/kodi/Summer [imm-…]/`."""
    windows = "\\" in output_path and "://" not in output_path
    separator = "\\" if windows else "/"
    path = output_path.rstrip("/\\")
    if folder_name:
        path = f"{path}{separator}{folder_name}"
    return path + separator


class KodiClient:
    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        *,
        timeout: float = DEFAULT_TIMEOUT_S,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        token = base64.b64encode(f"{username}:{password}".encode()).decode()
        headers = {"Authorization": f"Basic {token}"} if username or password else {}
        self._http = httpx2.AsyncClient(
            base_url=base_url.rstrip("/"), headers=headers, timeout=timeout, transport=transport
        )
        self._id = 0

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self._http.aclose()

    async def call(self, method: str, params: Mapping[str, Any] | None = None) -> Any:
        self._id += 1
        body: dict[str, Any] = {"jsonrpc": "2.0", "id": self._id, "method": method}
        if params is not None:
            body["params"] = dict(params)
        try:
            response = await self._http.post("/jsonrpc", json=body)
        except httpx2.HTTPError as exc:
            raise KodiUnreachableError(f"Kodi did not answer: {exc!r}") from exc
        if response.status_code in (401, 403):
            raise KodiAuthError("Kodi rejected the user name or the password")
        if response.status_code >= 400:
            raise KodiError(f"Kodi answered {response.status_code} to {method}")
        try:
            answer = response.json()
        except ValueError as exc:
            raise KodiError(f"Kodi gave no JSON to {method}") from exc
        if "error" in answer:
            error = answer["error"] or {}
            raise KodiError(f"Kodi refused {method}: {error.get('message', error)}")
        return answer.get("result")

    async def version(self) -> str:
        result = await self.call("Application.GetProperties", {"properties": ["version"]})
        version = (result or {}).get("version") or {}
        return f"{version.get('major', '?')}.{version.get('minor', '?')}"

    async def can_open(self, directory: str) -> bool:
        """Whether Kodi reaches the folder right now (a network share may be down)."""
        try:
            await self.call("Files.GetDirectory", {"directory": directory, "media": "video"})
        except KodiUnreachableError:
            raise
        except KodiError:
            return False
        return True

    async def shows(self) -> dict[UUID, int]:
        """The shows of the app that Kodi knows: Immich album id -> Kodi id. Kodi gives its
        shows new ids when they are refreshed, so they are never kept."""
        result = await self.call("VideoLibrary.GetTVShows", {"properties": ["uniqueid"]})
        shows: dict[UUID, int] = {}
        for show in (result or {}).get("tvshows") or []:
            unique = (show.get("uniqueid") or {}).get(UNIQUE_ID_TYPE)
            try:
                shows[UUID(str(unique))] = int(show["tvshowid"])
            except (KeyError, TypeError, ValueError):
                continue
        return shows

    async def scan(self, directory: str) -> None:
        await self.call("VideoLibrary.Scan", {"directory": directory, "showdialogs": False})

    async def clean(self, directory: str) -> None:
        """Remove from the library what is no longer in `directory`, and nothing elsewhere."""
        await self.call(
            "VideoLibrary.Clean",
            {"directory": directory, "content": "tvshows", "showdialogs": False},
        )

    async def refresh_show(self, show_id: int) -> None:
        await self.call(
            "VideoLibrary.RefreshTVShow",
            {"tvshowid": show_id, "ignorenfo": False, "refreshepisodes": True},
        )

    async def remove_show(self, show_id: int) -> None:
        await self.call("VideoLibrary.RemoveTVShow", {"tvshowid": show_id})


async def tell_kodi(
    client: KodiClient,
    output_path: str,
    changed: Mapping[UUID, str],
    gone: Collection[UUID],
) -> list[str]:
    """Make Kodi notice what changed. `changed` maps the albums whose files changed to their
    folders; `gone` are albums that are no longer shown. Kodi runs these as jobs one after
    another, in the order they are sent. Raises KodiError when Kodi can not be told now, or when
    it can not open the output folder or the folder of a changed show: a clean then would take
    their episodes for removed."""
    done: list[str] = []
    if not changed and not gone:
        return done
    root = folder_path(output_path)
    if not await client.can_open(root):
        raise KodiError(f"Kodi can not open {root} now")
    known = await client.shows()
    for album in sorted(gone, key=str):
        if album in known:
            await client.remove_show(known[album])
            done.append(f"Kodi: removed the show of album {album}")
    for album in sorted(changed.keys() & known.keys(), key=str):
        folder = folder_path(output_path, changed[album])
        # A show with files that Kodi does not find: a clean now would remove its episodes, and
        # their watched marks with them.
        if not await client.can_open(folder):
            raise KodiError(f"Kodi can not open {folder} now")
    for album in sorted(changed.keys() & known.keys(), key=str):
        await client.clean(folder_path(output_path, changed[album]))
    if changed:
        await client.scan(root)
        done.append("Kodi: scanned the library")
    for album in sorted(changed.keys() & known.keys(), key=str):
        await client.refresh_show(known[album])
        done.append(f"Kodi: refreshed the show of album {album}")
    return done
