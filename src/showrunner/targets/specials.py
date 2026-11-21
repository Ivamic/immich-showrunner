# SPDX-License-Identifier: AGPL-3.0-or-later
"""The files of the slideshows of a show.

With a folder of slideshows (D-102), the slideshow itself lies there, in the folder of its
album, and each output folder gets a link to it next to its NFO in `Specials`: one file on the
disk for every media server. Without one, each output folder gets a copy.

The names stay the same for the same year and part (checked on Jellyfin 12.4 and Kodi 21.3: a
file replaced under the same name keeps its watched marks)."""

from collections.abc import Callable
from pathlib import PurePosixPath

from showrunner.model.naming import special_file_stem
from showrunner.model.show import Show
from showrunner.targets.base import SLIDESHOWS, DesiredFile, FileKind, VideoSource
from showrunner.targets.nfo import special_nfo

SPECIALS_FOLDER = "Specials"
VIDEO_EXTENSION = ".mp4"


def store_file(folder_name: str, year: int, part: int) -> PurePosixPath:
    """Where a slideshow lies in the folder of slideshows."""
    return PurePosixPath(folder_name) / f"{special_file_stem(year, part)}{VIDEO_EXTENSION}"


def special_files(
    show: Show,
    root: PurePosixPath,
    stem: Callable[[int, int], str],
    store: PurePosixPath | None = None,
) -> list[DesiredFile]:
    """The slideshows of `show` in an output folder: links into `store` (the folder of
    slideshows as the media server sees it), or copies without one."""
    files: list[DesiredFile] = []
    base = root / SPECIALS_FOLDER
    for special in show.specials:
        name = stem(special.year, special.part)
        video = VideoSource(show.album_id, special)
        if store is not None:
            files.append(
                DesiredFile(
                    path=base / f"{name}{VIDEO_EXTENSION}",
                    kind=FileKind.LINK,
                    album_id=show.album_id,
                    link_target=store / store_file(root.as_posix(), special.year, special.part),
                    video=video,
                )
            )
        else:
            files.append(
                DesiredFile(
                    path=base / f"{name}{VIDEO_EXTENSION}",
                    kind=FileKind.VIDEO,
                    album_id=show.album_id,
                    video=video,
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


class SlideshowStore:
    """The folder of slideshows as a target: the slideshows of each album, nothing else."""

    name = SLIDESHOWS

    def files(self, show: Show, folder_name: str, artwork: object = None) -> list[DesiredFile]:
        return [
            DesiredFile(
                path=store_file(folder_name, special.year, special.part),
                kind=FileKind.VIDEO,
                album_id=show.album_id,
                video=VideoSource(show.album_id, special),
            )
            for special in show.specials
        ]
