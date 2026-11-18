# SPDX-License-Identifier: AGPL-3.0-or-later
"""The files of a show for Kodi (checked on Kodi 21.3, "Local information only"):

<show folder>/tvshow.nfo
<show folder>/poster.jpg                              drawn, or the cover of the album
<show folder>/landscape.jpg, fanart.jpg, clearlogo.png        drawn
<show folder>/Season 2024/poster.jpg                  drawn; set on the season by the app
<show folder>/.actors/<name_of_person>.jpg            the face of a person, from Immich
<show folder>/Season 2024/<date time [id]>.mp4        a link
<show folder>/Season 2024/<date time [id]>.nfo
<show folder>/Season 2024/<date time [id]>-thumb.jpg  the preview of the video

The file name holds the date of filming, by which Kodi recognises an episode, and never the
episode number: Kodi ties its watched marks to the path, and the numbers move when a video is
inserted in the middle. The season and the number come from the NFO.
"""

from pathlib import PurePosixPath
from uuid import UUID

from showrunner.artwork.jobs import ShowArtwork
from showrunner.artwork.style import OutputKind
from showrunner.model.naming import (
    kodi_actor_file_name,
    kodi_episode_file_stem,
    season_folder_name,
)
from showrunner.model.show import Show
from showrunner.targets.artwork import POSTER_NAME, SEASON_POSTER_NAME, picture_files
from showrunner.targets.base import KODI, DesiredFile, FileKind, ImageSource
from showrunner.targets.kodi.client import kodi_file_path
from showrunner.targets.nfo import episode_nfo, show_nfo

SHOW_NFO_NAME = "tvshow.nfo"
PICTURE_NAMES = {
    OutputKind.SERIES_POSTER: POSTER_NAME,
    OutputKind.LANDSCAPE: "landscape.jpg",
    OutputKind.FANART: "fanart.jpg",
    OutputKind.LOGO: "clearlogo.png",
}
THUMB_SUFFIX = "-thumb.jpg"
ACTORS_FOLDER = ".actors"
# Immich gives no version of a face: it is downloaded once.
FACE_VERSION = "face"


class KodiLayout:
    name = KODI

    def __init__(self, output_path: str = "") -> None:
        """`output_path` is the output folder as Kodi sees it (`smb://…`), for the paths of the
        posters of seasons in the NFO of the show; without it the seasons get no posters."""
        self.output_path = output_path

    def files(
        self, show: Show, folder_name: str, artwork: ShowArtwork | None = None
    ) -> list[DesiredFile]:
        root = PurePosixPath(folder_name)
        files = [
            DesiredFile(
                path=root / SHOW_NFO_NAME,
                kind=FileKind.SHOW_NFO,
                album_id=show.album_id,
                content=show_nfo(show, self._season_posters(folder_name, artwork)),
            )
        ]
        files += picture_files(show, root, artwork, PICTURE_NAMES)
        faces: dict[str, UUID] = {}
        for episode in show.episodes:
            base = root / season_folder_name(episode.season)
            stem = kodi_episode_file_stem(episode.filmed_at, episode.asset_id)
            files.append(
                DesiredFile(
                    path=base / f"{stem}{episode.extension}",
                    kind=FileKind.LINK,
                    album_id=show.album_id,
                    asset_id=episode.asset_id,
                    link_target=episode.link_target,
                )
            )
            files.append(
                DesiredFile(
                    path=base / f"{stem}.nfo",
                    kind=FileKind.EPISODE_NFO,
                    album_id=show.album_id,
                    asset_id=episode.asset_id,
                    content=episode_nfo(episode),
                )
            )
            files.append(
                DesiredFile(
                    path=base / f"{stem}{THUMB_SUFFIX}",
                    kind=FileKind.IMAGE,
                    album_id=show.album_id,
                    asset_id=episode.asset_id,
                    image=ImageSource(episode.asset_id, episode.picture_version),
                )
            )
            for person in episode.people:
                faces.setdefault(kodi_actor_file_name(person.name), person.id)
        for file_name, person_id in sorted(faces.items()):
            files.append(
                DesiredFile(
                    path=root / ACTORS_FOLDER / file_name,
                    kind=FileKind.IMAGE,
                    album_id=show.album_id,
                    image=ImageSource(person_id, FACE_VERSION, of_person=True),
                )
            )
        return files

    def _season_posters(self, folder_name: str, artwork: ShowArtwork | None) -> dict[int, str]:
        if not self.output_path or not artwork:
            return {}
        return {
            season: kodi_file_path(
                self.output_path,
                PurePosixPath(folder_name) / season_folder_name(season) / SEASON_POSTER_NAME,
            )
            for kind, season in artwork
            if kind is OutputKind.SEASON_POSTER and season is not None
        }
