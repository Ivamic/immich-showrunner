# SPDX-License-Identifier: AGPL-3.0-or-later
"""The files of the slideshows of a show, for every target: in its `Specials` folder, a video
the app draws and its NFO, under a name that stays the same for the same year and part
(checked on Jellyfin 12.4 and Kodi 21.3: a file replaced under the same name keeps its watched
marks)."""

from collections.abc import Callable
from pathlib import PurePosixPath

from showrunner.model.show import Show
from showrunner.targets.base import DesiredFile, FileKind, VideoSource
from showrunner.targets.nfo import special_nfo

SPECIALS_FOLDER = "Specials"
VIDEO_EXTENSION = ".mp4"


def special_files(
    show: Show, root: PurePosixPath, stem: Callable[[int, int], str]
) -> list[DesiredFile]:
    files: list[DesiredFile] = []
    base = root / SPECIALS_FOLDER
    for special in show.specials:
        name = stem(special.year, special.part)
        files.append(
            DesiredFile(
                path=base / f"{name}{VIDEO_EXTENSION}",
                kind=FileKind.VIDEO,
                album_id=show.album_id,
                video=VideoSource(show.album_id, special),
            )
        )
        files.append(
            DesiredFile(
                path=base / f"{name}.nfo",
                kind=FileKind.EPISODE_NFO,
                album_id=show.album_id,
                content=special_nfo(show.album_id, special),
            )
        )
    return files
