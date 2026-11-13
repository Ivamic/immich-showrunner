# SPDX-License-Identifier: AGPL-3.0-or-later
"""The files of a show for Jellyfin:

<show folder>/tvshow.nfo
<show folder>/Season 2024/<stem>.mp4   a link
<show folder>/Season 2024/<stem>.nfo
"""

from pathlib import PurePosixPath

from showrunner.model.naming import season_folder_name
from showrunner.model.show import Show
from showrunner.targets.base import DesiredFile, FileKind
from showrunner.targets.jellyfin.nfo import episode_nfo, show_nfo

SHOW_NFO_NAME = "tvshow.nfo"


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
        return files
