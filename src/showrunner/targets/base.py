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


@dataclass(frozen=True)
class DesiredFile:
    """A file that should exist. `path` is relative to the output folder. A link has a
    `link_target`, any other file has `content`."""

    path: PurePosixPath
    kind: FileKind
    album_id: UUID
    asset_id: UUID | None = None
    link_target: PurePosixPath | None = None
    content: bytes | None = None

    def __post_init__(self) -> None:
        if self.path.is_absolute() or ".." in self.path.parts or not self.path.parts:
            raise ValueError(f"not a path inside the output folder: {str(self.path)!r}")
        if (self.kind is FileKind.LINK) != (self.link_target is not None):
            raise ValueError("a link needs a target, and only a link has one")
        if (self.kind is FileKind.LINK) == (self.content is not None):
            raise ValueError("a file that is not a link needs content, and a link has none")
        if self.link_target is not None and not self.link_target.is_absolute():
            raise ValueError("the target of a link must be an absolute path")

    @property
    def content_hash(self) -> str | None:
        return None if self.content is None else hashlib.sha256(self.content).hexdigest()


class Target(Protocol):
    name: str

    def files(self, show: Show, folder_name: str) -> list[DesiredFile]:
        """The files of `show` under the folder `folder_name` of the output folder."""
        ...
