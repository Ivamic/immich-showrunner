# SPDX-License-Identifier: AGPL-3.0-or-later
"""Async HTTP client for the Immich API. It only reads: the API key it is meant to be used with
has no permission to change anything."""

from collections.abc import AsyncIterator
from types import TracebackType
from typing import Any, Self
from uuid import UUID

import httpx2

from showrunner.immich.models import (
    Album,
    ApiKeyInfo,
    Asset,
    ImmichUser,
    LoginResult,
    SearchPage,
    ServerVersion,
)

DEFAULT_TIMEOUT_S = 30.0
SEARCH_PAGE_SIZE = 500

# What the app reads with. `user.read` tells whose key it is.
REQUIRED_PERMISSIONS = frozenset(
    {"album.read", "asset.read", "asset.view", "person.read", "user.read"}
)
ALL_PERMISSIONS = "all"


class ImmichError(Exception):
    """Base class for errors talking to Immich."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        # HTTP status of the answer of Immich; None when there was no answer.
        self.status = status


class ImmichUnreachableError(ImmichError):
    """The server did not answer (wrong URL, network problem, timeout)."""


class ImmichAuthError(ImmichError):
    """The API key was rejected."""


class ImmichPermissionError(ImmichError):
    """The API key lacks a permission required by the endpoint."""


class NotJpegError(ImmichError):
    """The preview is not a JPEG picture (Immich can be set to make WebP previews)."""


def api_base_url(url: str) -> str:
    url = url.rstrip("/")
    return url if url.endswith("/api") else url + "/api"


class ImmichClient:
    """Thin wrapper over the Immich REST API. Use as an async context manager."""

    def __init__(
        self,
        base_url: str,
        api_key: str | None,
        *,
        timeout: float = DEFAULT_TIMEOUT_S,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        """Without `api_key` only signing in works; the calls that take an Immich session token
        use it instead."""
        headers = {"Accept": "application/json"}
        if api_key:
            headers["x-api-key"] = api_key
        self._http = httpx2.AsyncClient(
            base_url=api_base_url(base_url), headers=headers, timeout=timeout, transport=transport
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx2.Response:
        try:
            response = await self._http.request(method, path, **kwargs)
        except httpx2.HTTPError as exc:
            raise ImmichUnreachableError(f"Immich did not answer: {exc!r}") from exc
        if response.status_code == 401:
            raise ImmichAuthError("Immich rejected the API key", 401)
        if response.status_code == 403:
            raise ImmichPermissionError(_message(response), 403)
        if response.status_code >= 400:
            raise ImmichError(
                f"Immich answered {response.status_code} to {method} {path}: {_message(response)}",
                response.status_code,
            )
        return response

    async def server_version(self) -> ServerVersion:
        response = await self._request("GET", "/server/version")
        return ServerVersion.model_validate(response.json())

    async def current_user(self) -> ImmichUser:
        response = await self._request("GET", "/users/me")
        return ImmichUser.model_validate(response.json())

    # --- signing in: these take the token of an Immich session ---------------------------------

    async def login(self, email: str, password: str) -> LoginResult:
        response = await self._request(
            "POST", "/auth/login", json={"email": email, "password": password}
        )
        return LoginResult.model_validate(response.json())

    async def logout(self, token: str) -> None:
        await self._request("POST", "/auth/logout", headers=_bearer(token))

    async def api_keys(self, token: str) -> list[ApiKeyInfo]:
        response = await self._request("GET", "/api-keys", headers=_bearer(token))
        return [ApiKeyInfo.model_validate(item) for item in response.json()]

    async def create_api_key(self, token: str, name: str, permissions: list[str]) -> str:
        response = await self._request(
            "POST",
            "/api-keys",
            headers=_bearer(token),
            json={"name": name, "permissions": permissions},
        )
        return str(response.json()["secret"])

    async def delete_api_key(self, token: str, key_id: UUID) -> None:
        await self._request("DELETE", f"/api-keys/{key_id}", headers=_bearer(token))

    async def api_key_info(self) -> ApiKeyInfo:
        response = await self._request("GET", "/api-keys/me")
        return ApiKeyInfo.model_validate(response.json())

    async def albums(self) -> list[Album]:
        """Every album the user of the key can see: its own and the ones shared with it."""
        response = await self._request("GET", "/albums")
        return [Album.model_validate(item) for item in response.json()]

    async def preview(self, asset_id: UUID) -> bytes:
        """The preview picture of an asset: the same picture Immich shows, as JPEG."""
        response = await self._request(
            "GET",
            f"/assets/{asset_id}/thumbnail",
            params={"size": "preview"},
            headers={"Accept": "image/*"},
        )
        return _jpeg(response, f"the preview of asset {asset_id}")

    async def thumbnail(self, asset_id: UUID, size: str = "thumbnail") -> tuple[bytes, str]:
        """A picture of an asset for the page, in whatever format Immich makes it."""
        response = await self._request(
            "GET",
            f"/assets/{asset_id}/thumbnail",
            params={"size": size},
            headers={"Accept": "image/*"},
        )
        return response.content, response.headers.get("content-type", "image/jpeg")

    async def person_picture(self, person_id: UUID) -> bytes:
        """The face of a person, as Immich shows it in the list of people."""
        response = await self._request(
            "GET", f"/people/{person_id}/thumbnail", headers={"Accept": "image/*"}
        )
        return _jpeg(response, f"the picture of person {person_id}")

    async def album_videos(self, album_id: UUID) -> AsyncIterator[Asset]:
        """The videos of an album, with their descriptions and the people that the user of the
        key may see. Immich does not return trashed and hidden assets here."""
        page: str | None = "1"
        while page is not None:
            response = await self._request(
                "POST",
                "/search/metadata",
                json={
                    "albumIds": [str(album_id)],
                    "type": "VIDEO",
                    "withExif": True,
                    "withPeople": True,
                    "size": SEARCH_PAGE_SIZE,
                    "page": int(page),
                },
            )
            result = SearchPage.model_validate(response.json()["assets"])
            for asset in result.items:
                yield asset
            page = result.next_page


def missing_permissions(info: ApiKeyInfo) -> frozenset[str]:
    """Permissions the key needs and does not have."""
    if ALL_PERMISSIONS in info.permissions:
        return frozenset()
    return REQUIRED_PERMISSIONS - set(info.permissions)


def excess_permissions(info: ApiKeyInfo) -> frozenset[str]:
    """Permissions the key has and the app never uses. A key with them could change the library;
    the app reports them, so that the key can be replaced by a read-only one."""
    return frozenset(info.permissions) - REQUIRED_PERMISSIONS


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _jpeg(response: httpx2.Response, what: str) -> bytes:
    media_type = response.headers.get("content-type", "").split(";")[0].strip()
    if media_type != "image/jpeg":
        raise NotJpegError(
            f"{what} is {media_type or 'of no type'}, not JPEG; "
            "set the preview format of Immich to JPEG",
            response.status_code,
        )
    return response.content


def _message(response: httpx2.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:200]
    message = body.get("message") if isinstance(body, dict) else None
    return str(message) if message else response.text[:200]
