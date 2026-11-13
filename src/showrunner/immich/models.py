# SPDX-License-Identifier: AGPL-3.0-or-later
"""The parts of Immich API answers that the app uses (checked against Immich 3.4)."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class ImmichModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore")


class ServerVersion(ImmichModel):
    major: int
    minor: int
    patch: int

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


class ApiKeyInfo(ImmichModel):
    id: UUID
    name: str
    permissions: list[str]


class AlbumUserInfo(ImmichModel):
    id: UUID
    name: str


class AlbumUser(ImmichModel):
    user: AlbumUserInfo
    role: str


class Album(ImmichModel):
    id: UUID
    album_name: str
    description: str = ""
    album_thumbnail_asset_id: UUID | None = None
    asset_count: int = 0
    updated_at: datetime
    # Changes when a video of the album changes (its description, for example); `updated_at` does
    # not. Renaming the album changes only `updated_at`. Both are needed to notice a change.
    last_modified_asset_timestamp: datetime | None = None
    album_users: list[AlbumUser] = Field(default_factory=list)

    @property
    def owner_id(self) -> UUID | None:
        return next((u.user.id for u in self.album_users if u.role == "owner"), None)


class Person(ImmichModel):
    id: UUID
    name: str = ""


class ExifInfo(ImmichModel):
    description: str | None = None


class Asset(ImmichModel):
    id: UUID
    type: str
    owner_id: UUID
    original_path: str
    original_file_name: str
    # The time of filming on the clock of the place of filming, written as if it were UTC.
    local_date_time: datetime
    # Milliseconds since Immich 3.
    duration: int | None = None
    is_trashed: bool = False
    is_offline: bool = False
    visibility: str = "timeline"
    updated_at: datetime
    exif_info: ExifInfo | None = None
    people: list[Person] = Field(default_factory=list)
    # A short hash of the thumbnail; it changes when Immich makes the thumbnail again.
    thumbhash: str | None = None

    @property
    def description(self) -> str:
        return (self.exif_info.description if self.exif_info else None) or ""


class SearchPage(ImmichModel):
    items: list[Asset]
    next_page: str | None = None
