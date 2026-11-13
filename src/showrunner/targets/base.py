# SPDX-License-Identifier: AGPL-3.0-or-later
"""What a target hands to the sync: the files that should exist in the output folder."""

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Protocol
from uuid import UUID

from showrunner.model.show import Show


class FileKind(StrEnum):
    LINK = "link"  # a symbolic link to a video of the Immich library
    SHOW_NFO = "show_nfo"
    EPISODE_NFO = "episode_nfo"
    # A picture taken from Immich: downloaded only when it is new or changed there.
    IMAGE = "image"


@dataclass(frozen=True)
class ImageSource:
    """Which picture of Immich a file holds. `version` changes when the picture changes there, so
    that it is downloaded again only then."""

    asset_id: UUID
    version: str


@dataclass(frozen=True)
class DesiredFile:
    """A file that should exist. `path` is relative to the output folder.

    A link has a `link_target`. A picture has an `image` source; its `content` is filled in only
    when it has to be downloaded. Any other file has `content`."""

    path: PurePosixPath
    kind: FileKind
    album_id: UUID
    asset_id: UUID | None = None
    link_target: PurePosixPath | None = None
    content: bytes | None = None
    image: ImageSource | None = None

    def __post_init__(self) -> None:
        if self.path.is_absolute() or ".." in self.path.parts or not self.path.parts:
            raise ValueError(f"not a path inside the output folder: {str(self.path)!r}")
        is_link = self.kind is FileKind.LINK
        is_image = self.kind is FileKind.IMAGE
        if is_link != (self.link_target is not None):
            raise ValueError("a link needs a target, and only a link has one")
        if is_image != (self.image is not None):
            raise ValueError("a picture needs an image source, and only a picture has one")
        if is_link and self.content is not None:
            raise ValueError("a link has no content")
        if not is_link and not is_image and self.content is None:
            raise ValueError("a file that is not a link or a picture needs content")
        if self.link_target is not None and not self.link_target.is_absolute():
            raise ValueError("the target of a link must be an absolute path")

    @property
    def content_hash(self) -> str | None:
        return None if self.content is None else hashlib.sha256(self.content).hexdigest()

    @property
    def source_version(self) -> str | None:
        return self.image.version if self.image is not None else None


class Target(Protocol):
    name: str

    def files(self, show: Show, folder_name: str) -> list[DesiredFile]:
        """The files of `show` under the folder `folder_name` of the output folder."""
        ...
