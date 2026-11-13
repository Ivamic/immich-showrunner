# SPDX-License-Identifier: AGPL-3.0-or-later
"""The files of a show for Jellyfin:

<show folder>/tvshow.nfo
<show folder>/poster.jpg                      the cover of the album
<show folder>/Season 2024/<stem>.mp4          a link
<show folder>/Season 2024/<stem>.nfo
<show folder>/Season 2024/<stem>-thumb.jpg    the preview of the video
"""

from pathlib import PurePosixPath

from showrunner.model.naming import season_folder_name
from showrunner.model.show import Show
from showrunner.targets.base import DesiredFile, FileKind, ImageSource
from showrunner.targets.jellyfin.nfo import episode_nfo, show_nfo

SHOW_NFO_NAME = "tvshow.nfo"
POSTER_NAME = "poster.jpg"
THUMB_SUFFIX = "-thumb.jpg"


class JellyfinLayout:
    name = "jellyfin"

    def files(self, show: Show, folder_name: str) -> list[DesiredFile]:
        root = PurePosixPath(folder_name)
        files = [
            DesiredFile(
                path=root / SHOW_NFO_NAME,
                kind=FileKind.SHOW_NFO,
                album_id=show.album_id,
                content=show_nfo(show),
            )
        ]
        if show.cover_asset_id is not None:
            files.append(
                DesiredFile(
                    path=root / POSTER_NAME,
                    kind=FileKind.IMAGE,
                    album_id=show.album_id,
                    # Another cover is another asset; a new preview of the same asset is not
                    # worth a download on every pass.
                    image=ImageSource(show.cover_asset_id, str(show.cover_asset_id)),
                )
            )
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
