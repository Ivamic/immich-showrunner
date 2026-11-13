# SPDX-License-Identifier: AGPL-3.0-or-later
"""Names of folders and files in the output folder.

A name is built once from data that never changes (the id, the date of filming, the original file
name) and never holds an episode number: the media server ties its watched marks to the path, so a
path must survive renaming the album or the video and inserting a video in the middle."""

import re
import unicodedata
from datetime import datetime
from pathlib import PurePosixPath
from uuid import UUID

# Characters that are not allowed in a file name on Windows or over SMB, and the path separator.
_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_SPACES = re.compile(r"\s+")
# A file name may take 255 bytes on common Linux file systems; leave room for the id, the
# extension and the suffixes of files next to the video (`-thumb.jpg`, `.nfo`).
MAX_NAME_BYTES = 180
ID_LENGTH = 8
SHOW_ID_PREFIX = "imm-"
FALLBACK_NAME = "untitled"


def safe_name(text: str, *, max_bytes: int = MAX_NAME_BYTES) -> str:
    """Make `text` a single path component: no separators, no control characters, no leading or
    trailing dots and spaces, not longer than `max_bytes` in UTF-8."""
    text = unicodedata.normalize("NFC", text)
    text = _FORBIDDEN.sub(" ", text)
    text = _SPACES.sub(" ", text).strip(" .")
    encoded = text.encode("utf-8")[:max_bytes]
    text = encoded.decode("utf-8", errors="ignore").strip(" .")
    return text or FALLBACK_NAME


def short_id(value: UUID) -> str:
    return value.hex[:ID_LENGTH]


def show_folder_name(album_name: str, album_id: UUID) -> str:
    """`Summer at the lake [imm-97769e09]`. Kept as it was first created when the album is
    renamed: the title lives in the metadata."""
    return f"{safe_name(album_name)} [{SHOW_ID_PREFIX}{short_id(album_id)}]"


def season_folder_name(season: int) -> str:
    return f"Season {season:02d}"


def episode_file_stem(filmed_at: datetime, original_file_name: str, asset_id: UUID) -> str:
    """`2024-07-15 VID_20240715_143211 [712f0482]`: sorts by date in a file manager and is unique
    by the id."""
    stem = PurePosixPath(original_file_name.replace("\\", "/")).stem
    return f"{filmed_at:%Y-%m-%d} {safe_name(stem, max_bytes=120)} [{short_id(asset_id)}]"


def file_extension(path: str) -> str:
    """The extension of the original file, lower case, with the dot; empty when there is none or
    it does not look like one."""
    suffix = PurePosixPath(path.replace("\\", "/")).suffix.lower()
    return suffix if re.fullmatch(r"\.[a-z0-9]{1,5}", suffix) else ""
