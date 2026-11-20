# SPDX-License-Identifier: AGPL-3.0-or-later
"""A small Immich for the tests: albums with videos and photos, answered the way Immich 3.4
answers."""

import io
import json
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import httpx2
from PIL import Image

from showrunner.immich.client import ImmichClient

OWNER = "7be25f09-c8d5-437a-993a-9cfde9b73b67"


def album_id(n: int) -> UUID:
    return UUID(f"{n:08x}-aaaa-4000-8000-000000000000")


def asset_id(n: int) -> UUID:
    return UUID(f"{n:08x}-0000-4000-8000-000000000000")


def webp_picture(mode: str = "RGB") -> bytes:
    """A small real WebP picture, the way Immich makes previews when set to WebP."""
    out = io.BytesIO()
    color = (200, 30, 30, 128) if mode == "RGBA" else (200, 30, 30)
    Image.new(mode, (64, 36), color).save(out, "WEBP")
    return out.getvalue()


@dataclass
class FakeImmich:
    albums: dict[UUID, dict[str, Any]] = field(default_factory=dict)
    videos: dict[UUID, list[dict[str, Any]]] = field(default_factory=dict)
    # Paths that answer with an error, by their start.
    broken: dict[str, int] = field(default_factory=dict)
    # What the previews are served as.
    preview_type: str = "image/jpeg"
    requests: list[str] = field(default_factory=list)
    photos: dict[UUID, list[dict[str, Any]]] = field(default_factory=dict)
    # The pictures of the photos, by asset: what `fullsize` gives; `preview` gives a smaller copy.
    photo_files: dict[str, bytes] = field(default_factory=dict)

    def add_album(self, n: int, name: str, *, stamp: str = "2026-01-01T00:00:00.000Z") -> UUID:
        key = album_id(n)
        self.albums[key] = {
            "id": str(key),
            "albumName": name,
            "description": "",
            "assetCount": 0,
            "updatedAt": stamp,
            "lastModifiedAssetTimestamp": stamp,
            "albumUsers": [{"user": {"id": OWNER, "name": "Owner"}, "role": "owner"}],
        }
        self.videos[key] = []
        self.photos[key] = []
        return key

    def add_photo(
        self,
        album: UUID,
        n: int,
        when: str,
        content: bytes,
        *,
        size: tuple[int, int] = (64, 48),
        checksum: str = "sum1",
    ) -> UUID:
        key = asset_id(n)
        self.photos[album].append(
            {
                "id": str(key),
                "type": "IMAGE",
                "ownerId": OWNER,
                "originalPath": f"/data/upload/owner/p{n}.jpg",
                "originalFileName": f"IMG_{n}.jpg",
                "localDateTime": when + ".000Z",
                "updatedAt": "2026-01-01T00:00:00.000Z",
                "exifInfo": {"description": "", "latitude": 43.7, "longitude": 7.26},
                "people": [],
                "checksum": checksum,
                "width": size[0],
                "height": size[1],
                "originalMimeType": "image/jpeg",
            }
        )
        self.photo_files[str(key)] = content
        return key

    def add_video(
        self, album: UUID, n: int, when: str, *, description: str = "", path: str | None = None
    ) -> UUID:
        key = asset_id(n)
        self.videos[album].append(
            {
                "id": str(key),
                "type": "VIDEO",
                "ownerId": OWNER,
                "originalPath": path or f"/data/upload/owner/v{n}.mp4",
                "originalFileName": f"VID_{n}.mp4",
                "localDateTime": when + ".000Z",
                "updatedAt": "2026-01-01T00:00:00.000Z",
                "exifInfo": {"description": description},
                "people": [],
                "thumbhash": "hash1",
            }
        )
        return key

    def touch(self, album: UUID, stamp: str) -> None:
        self.albums[album]["updatedAt"] = stamp
        self.albums[album]["lastModifiedAssetTimestamp"] = stamp

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        self.requests.append(f"{request.method} {path}")
        for start, status in self.broken.items():
            if path.startswith(start):
                return httpx2.Response(status, json={"message": "broken"})
        if path == "/api/albums":
            return httpx2.Response(200, json=list(self.albums.values()))
        if path.startswith("/api/people/") and path.endswith("/thumbnail"):
            body = f"JPEG face {path.split('/')[3]}".encode()
            return httpx2.Response(200, content=body, headers={"content-type": "image/jpeg"})
        if path.startswith("/api/assets/") and path.endswith("/original"):
            asset = path.split("/")[3]
            if asset in self.photo_files:
                content = self.photo_files[asset]
                return httpx2.Response(200, content=content, headers={"content-type": "image/jpeg"})
        if path.startswith("/api/assets/") and path.endswith("/thumbnail"):
            asset = path.split("/")[3]
            if asset in self.photo_files:
                return self._photo(asset, request.url.params.get("size", "thumbnail"))
            version = next(
                (
                    v.get("thumbhash", "")
                    for vs in self.videos.values()
                    for v in vs
                    if v["id"] == asset
                ),
                "cover",
            )
            body = (
                webp_picture()
                if self.preview_type == "image/webp"
                else f"JPEG {asset} {version}".encode()
            )
            return httpx2.Response(200, content=body, headers={"content-type": self.preview_type})
        if path == "/api/search/metadata":
            body = json.loads(request.content)
            album = UUID(body["albumIds"][0])
            items = self.photos[album] if body.get("type") == "IMAGE" else self.videos[album]
            return httpx2.Response(200, json={"assets": {"items": items, "nextPage": None}})
        return httpx2.Response(404, json={"message": "not found"})

    def _photo(self, asset: str, size: str) -> httpx2.Response:
        content = self.photo_files[asset]
        if size == "fullsize":
            # As Immich does for a photo that is a picture already: on to the original file.
            return httpx2.Response(302, headers={"location": f"/api/assets/{asset}/original"})
        try:
            with Image.open(io.BytesIO(content)) as picture:
                picture.thumbnail((max(1, picture.width // 2), max(1, picture.height // 2)))
                out = io.BytesIO()
                picture.convert("RGB").save(out, "WEBP")
        except OSError:  # not a picture: given as it is
            return httpx2.Response(200, content=content, headers={"content-type": "image/webp"})
        return httpx2.Response(200, content=out.getvalue(), headers={"content-type": "image/webp"})

    def client(self) -> ImmichClient:
        return ImmichClient(
            "http://immich.test", "key", transport=httpx2.MockTransport(self.handler)
        )
