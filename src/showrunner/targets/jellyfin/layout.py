# SPDX-License-Identifier: AGPL-3.0-or-later
"""The files of a show for Jellyfin:

<show folder>/tvshow.nfo
<show folder>/folder.jpg                      drawn (or poster.jpg: the cover of the album)
<show folder>/landscape.jpg, fanart.jpg, logo.png     drawn
<show folder>/Season 2024/poster.jpg          drawn
<show folder>/Season 2024/<stem>.mp4          a link
<show folder>/Season 2024/<stem>.nfo
<show folder>/Season 2024/<stem>-thumb.jpg    the preview of the video
"""

from pathlib import PurePosixPath

from showrunner.artwork.jobs import ShowArtwork
from showrunner.artwork.style import OutputKind
from showrunner.model.naming import season_folder_name
from showrunner.model.show import Show
from showrunner.targets.artwork import picture_files
from showrunner.targets.base import DesiredFile, FileKind, ImageSource
from showrunner.targets.nfo import episode_nfo, show_nfo

SHOW_NFO_NAME = "tvshow.nfo"
THUMB_SUFFIX = "-thumb.jpg"
# The drawn poster is folder.jpg, the cover of the album poster.jpg: Jellyfin keeps the size of
# a picture by its path and does not measure it again when the file is replaced, so a 2:3
# poster in place of a 16:9 cover would be shown cut to 16:9. Another name is another picture.
DRAWN_POSTER_NAME = "folder.jpg"
PICTURE_NAMES = {
    OutputKind.SERIES_POSTER: DRAWN_POSTER_NAME,
    OutputKind.LANDSCAPE: "landscape.jpg",
    OutputKind.FANART: "fanart.jpg",
    OutputKind.LOGO: "logo.png",
}


class JellyfinLayout:
    name = "jellyfin"

    def files(
        self, show: Show, folder_name: str, artwork: ShowArtwork | None = None
    ) -> list[DesiredFile]:
        root = PurePosixPath(folder_name)
        files = [
            DesiredFile(
                path=root / SHOW_NFO_NAME,
                kind=FileKind.SHOW_NFO,
                album_id=show.album_id,
                content=show_nfo(show),
            )
        ]
        files += picture_files(show, root, artwork, PICTURE_NAMES)
        for episode in show.episodes:
            base = root / season_folder_name(episode.season)
            files.append(
                DesiredFile(
                    path=base / f"{episode.file_stem}{episode.extension}",
                    kind=FileKind.LINK,
                    album_id=show.album_id,
                    asset_id=episode.asset_id,
                    link_target=episode.link_target,
                )
            )
            files.append(
                DesiredFile(
                    path=base / f"{episode.file_stem}.nfo",
                    kind=FileKind.EPISODE_NFO,
                    album_id=show.album_id,
                    asset_id=episode.asset_id,
                    content=episode_nfo(episode),
                )
            )
            files.append(
                DesiredFile(
                    path=base / f"{episode.file_stem}{THUMB_SUFFIX}",
                    kind=FileKind.IMAGE,
                    album_id=show.album_id,
                    asset_id=episode.asset_id,
                    image=ImageSource(episode.asset_id, episode.picture_version),
                )
            )
        return files
