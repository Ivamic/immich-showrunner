# SPDX-License-Identifier: AGPL-3.0-or-later
"""The files of the pictures the app draws for a show, for any target.

Without artwork (it is off, or the videos of the album are not looked at yet) the poster is the
cover of the album in Immich, as before. With artwork the drawn poster takes its place, and the
show gets a landscape picture, a backdrop, a logo and a poster for every season."""

from collections.abc import Mapping
from pathlib import PurePosixPath

from showrunner.artwork.jobs import ShowArtwork
from showrunner.artwork.style import OutputKind
from showrunner.model.naming import season_folder_name
from showrunner.model.show import Show
from showrunner.targets.base import DesiredFile, FileKind, ImageSource

POSTER_NAME = "poster.jpg"
SEASON_POSTER_NAME = "poster.jpg"
"""In the folder of the season. Jellyfin reads it; Kodi does not, and is given it by the app
(a `seasonNNNN-poster.jpg` in the folder of the show would make Kodi count thousands of empty
seasons)."""


def picture_files(
    show: Show,
    root: PurePosixPath,
    artwork: ShowArtwork | None,
    names: Mapping[OutputKind, str],
) -> list[DesiredFile]:
    """The pictures of the show: `names` gives the file name of each picture of the show."""
    files: list[DesiredFile] = []
    if artwork:
        for (kind, season), job in sorted(
            artwork.items(), key=lambda item: (item[0][0].value, item[0][1] or 0)
        ):
            if kind is OutputKind.SEASON_POSTER and season is not None:
                path = root / season_folder_name(season) / SEASON_POSTER_NAME
            elif kind in names:
                path = root / names[kind]
            else:
                continue
            files.append(
                DesiredFile(
                    path=path,
                    kind=FileKind.IMAGE,
                    album_id=show.album_id,
                    image=ImageSource.of_artwork(job),
                )
            )
        if (OutputKind.SERIES_POSTER, None) in artwork and OutputKind.SERIES_POSTER in names:
            return files  # the drawn poster takes the place of the cover
    if show.cover_asset_id is not None:
        files.append(
            DesiredFile(
                path=root / POSTER_NAME,
                kind=FileKind.IMAGE,
                album_id=show.album_id,
                # Another cover is another asset; a new preview of the same asset is not worth
                # a download on every pass.
                image=ImageSource(show.cover_asset_id, str(show.cover_asset_id)),
            )
        )
    return files
