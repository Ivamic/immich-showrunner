# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Jellyfin API, as far as the app needs it (checked on Jellyfin 12.4).

A plain scan of the library does not read an NFO file again once Jellyfin knows the episode, so
after every change the app asks Jellyfin to refresh the show."""

import base64
from pathlib import PurePosixPath
from types import TracebackType
from typing import Any, Self
from uuid import UUID

import httpx2

from showrunner.targets.jellyfin.nfo import UNIQUE_ID_TYPE

DEFAULT_TIMEOUT_S = 30.0


class JellyfinError(Exception):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class JellyfinUnreachableError(JellyfinError):
    """The server did not answer."""


class JellyfinAuthError(JellyfinError):
    """The API key was rejected."""


class JellyfinClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float = DEFAULT_TIMEOUT_S,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        self._http = httpx2.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f'MediaBrowser Token="{api_key}"'},
            timeout=timeout,
            transport=transport,
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self._http.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx2.Response:
        try:
            response = await self._http.request(method, path, **kwargs)
        except httpx2.HTTPError as exc:
            raise JellyfinUnreachableError(f"Jellyfin did not answer: {exc!r}") from exc
        if response.status_code in (401, 403):
            raise JellyfinAuthError("Jellyfin rejected the API key", response.status_code)
        if response.status_code >= 400:
            raise JellyfinError(
                f"Jellyfin answered {response.status_code} to {method} {path}",
                response.status_code,
            )
        return response

    async def version(self) -> str:
        response = await self._request("GET", "/System/Info")
        return str(response.json().get("Version", ""))

    async def library_id(self, folder: PurePosixPath) -> str | None:
        """The library that scans `folder` (the output folder, as Jellyfin sees it)."""
        response = await self._request("GET", "/Library/VirtualFolders")
        for library in response.json():
            locations = [PurePosixPath(location) for location in library.get("Locations") or []]
            if folder in locations:
                item_id = library.get("ItemId")
                return str(item_id) if item_id else None
        return None

    async def shows(self) -> dict[UUID, str]:
        """The shows of the app that Jellyfin knows: Immich album id -> Jellyfin item id."""
        response = await self._request(
            "GET",
            "/Items",
            params={"includeItemTypes": "Series", "recursive": "true", "fields": "ProviderIds"},
        )
        result: dict[UUID, str] = {}
        for item in response.json().get("Items", []):
            provider_ids = {k.lower(): v for k, v in (item.get("ProviderIds") or {}).items()}
            try:
                result[UUID(provider_ids[UNIQUE_ID_TYPE])] = str(item["Id"])
            except (KeyError, ValueError):
                continue
        return result

    async def refresh_show(self, item_id: str) -> None:
        """Read the files and the NFO of a show again: new and removed episodes, changed titles
        and numbers. Watched marks stay."""
        await self._request(
            "POST",
            f"/Items/{item_id}/Refresh",
            params={
                "Recursive": "true",
                "MetadataRefreshMode": "FullRefresh",
                "ImageRefreshMode": "Default",
                "ReplaceAllMetadata": "true",
            },
        )

    async def scan_library(self, library_id: str) -> None:
        """Look for new and removed shows in one library."""
        await self._request(
            "POST",
            f"/Items/{library_id}/Refresh",
            params={
                "Recursive": "true",
                "MetadataRefreshMode": "Default",
                "ImageRefreshMode": "Default",
            },
        )

    async def scan_all(self) -> None:
        await self._request("POST", "/Library/Refresh")

    async def admin_user_id(self) -> str:
        """An administrator: reading a whole item needs a user, and an API key has none."""
        response = await self._request("GET", "/Users")
        for user in response.json():
            if (user.get("Policy") or {}).get("IsAdministrator"):
                return str(user["Id"])
        raise JellyfinError("Jellyfin has no administrator to read items with")

    async def persons(self) -> list[dict[str, Any]]:
        response = await self._request("GET", "/Persons")
        return list(response.json().get("Items", []))

    async def item(self, item_id: str, user_id: str) -> dict[str, Any]:
        response = await self._request("GET", f"/Items/{item_id}", params={"userId": user_id})
        return dict(response.json())

    async def update_item(self, item_id: str, item: dict[str, Any]) -> None:
        await self._request("POST", f"/Items/{item_id}", json=item)

    async def set_primary_image(self, item_id: str, jpeg: bytes) -> None:
        await self._request(
            "POST",
            f"/Items/{item_id}/Images/Primary",
            content=base64.b64encode(jpeg),
            headers={"Content-Type": "image/jpeg"},
        )


async def tell_jellyfin(
    client: JellyfinClient,
    output_folder: PurePosixPath,
    changed_albums: set[UUID],
    gone_albums: set[UUID],
) -> list[str]:
    """Make Jellyfin notice what a sync changed. Returns what was done, for the log.

    A show Jellyfin already knows is refreshed by itself. A new show, or one whose album is no
    longer shared, needs a scan of the library."""
    done: list[str] = []
    if not changed_albums and not gone_albums:
        return done
    known = await client.shows()
    new = changed_albums - known.keys()
    if new or gone_albums:
        library = await client.library_id(output_folder)
        if library is not None:
            await client.scan_library(library)
            done.append("scanned the library")
        else:
            await client.scan_all()
            done.append("scanned all libraries (none has the output folder as its only path)")
    for album in sorted(changed_albums & known.keys(), key=str):
        await client.refresh_show(known[album])
        done.append(f"refreshed the show of album {album}")
    return done
