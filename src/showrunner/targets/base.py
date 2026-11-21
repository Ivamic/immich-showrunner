# SPDX-License-Identifier: AGPL-3.0-or-later
"""What a target hands to the sync: the files that should exist in the output folder."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Protocol
from uuid import UUID

from showrunner.artwork.jobs import ArtworkJob, ShowArtwork
from showrunner.model.show import Show, Special

# Names of the targets, as the registry keeps them.
JELLYFIN = "jellyfin"
KODI = "kodi"
SLIDESHOWS = "slideshows"


class FileKind(StrEnum):
    LINK = "link"  # a symbolic link to a video of the Immich library
    SHOW_NFO = "show_nfo"
    EPISODE_NFO = "episode_nfo"
    # A picture taken from Immich: downloaded only when it is new or changed there.
    IMAGE = "image"
    # A slideshow the app draws: drawn again only when its cut list changes.
    VIDEO = "video"


@dataclass(frozen=True)
class ImageSource:
    """Which picture a file holds: the preview of an asset of Immich, with `of_person` the face
    of a person (`asset_id` is then the id of the person), or with `artwork` a picture the app
    draws (`asset_id` is then the album). `version` changes when the picture changes, so that
    it is downloaded or drawn again only then."""

    asset_id: UUID
    version: str
    of_person: bool = False
    artwork: ArtworkJob | None = None

    @classmethod
    def of_artwork(cls, job: ArtworkJob) -> ImageSource:
        return cls(job.album_id, job.version, artwork=job)


@dataclass(frozen=True)
class VideoSource:
    """Which slideshow a file holds, and its version (that of its cut list)."""

    album_id: UUID
    special: Special

    @property
    def version(self) -> str:
        return self.special.version


@dataclass(frozen=True)
class DesiredFile:
    """A file that should exist. `path` is relative to the output folder.

    A link has a `link_target`. A picture has an `image` source; its `content` is filled in only
    when it has to be downloaded. A slideshow has a `video` source; the file drawn (`drawn`) and
    its hash are filled in only when it has to be written. Any other file has `content`."""

    path: PurePosixPath
    kind: FileKind
    album_id: UUID
    asset_id: UUID | None = None
    link_target: PurePosixPath | None = None
    content: bytes | None = None
    image: ImageSource | None = None
    video: VideoSource | None = None
    drawn: Path | None = None
    drawn_hash: str | None = None

    def __post_init__(self) -> None:
        if self.path.is_absolute() or ".." in self.path.parts or not self.path.parts:
            raise ValueError(f"not a path inside the output folder: {str(self.path)!r}")
        is_link = self.kind is FileKind.LINK
        is_image = self.kind is FileKind.IMAGE
        is_video = self.kind is FileKind.VIDEO
        if is_video and self.video is None:
            raise ValueError("a slideshow needs a video source")
        if self.video is not None and not (is_video or is_link):
            raise ValueError("only a slideshow or a link to one has a video source")
        if is_link != (self.link_target is not None):
            raise ValueError("a link needs a target, and only a link has one")
        if is_image != (self.image is not None):
            raise ValueError("a picture needs an image source, and only a picture has one")
        if is_link and self.content is not None:
            raise ValueError("a link has no content")
        if is_video and self.content is not None:
            raise ValueError("a slideshow is written from the file drawn, not from content")
        if not is_link and not is_image and not is_video and self.content is None:
            raise ValueError("a file that is not a link or a picture needs content")
        if self.link_target is not None and not self.link_target.is_absolute():
            raise ValueError("the target of a link must be an absolute path")

    @property
    def content_hash(self) -> str | None:
        if self.kind is FileKind.VIDEO:
            return self.drawn_hash
        return None if self.content is None else hashlib.sha256(self.content).hexdigest()

    @property
    def source_version(self) -> str | None:
        if self.video is not None:
            return self.video.version
        return self.image.version if self.image is not None else None


class Target(Protocol):
    name: str

    def files(
        self, show: Show, folder_name: str, artwork: ShowArtwork | None = None
    ) -> list[DesiredFile]:
        """The files of `show` under the folder `folder_name` of the output folder. With
        `artwork`, the pictures the app draws take the place of the album's cover."""
        ...
