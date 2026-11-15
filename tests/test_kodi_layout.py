# SPDX-License-Identifier: AGPL-3.0-or-later
"""The files of a show for Kodi: names Kodi 21.3 recognises, without the episode number."""

import re
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import PurePosixPath
from uuid import UUID

from showrunner.model.naming import kodi_actor_file_name, kodi_episode_file_stem
from showrunner.model.show import Episode, EpisodePerson, Show
from showrunner.targets.base import FileKind, ImageSource
from showrunner.targets.kodi.layout import KodiLayout

ALBUM = UUID("97769e09-f6ec-4d0b-86d0-3237df31f35b")
ASSET = UUID("1e05abcd-ba03-4739-a060-cea85f44e17d")
OTHER = UUID("da01ae15-0000-4000-8000-000000000000")
ANNA = UUID("8800ba4a-52a0-4f68-944a-6587ea5ff3c2")
BORIS = UUID("8800ba4a-0000-4000-8000-000000000002")
FOLDER = "Summer [imm-97769e09]"


def episode(
    asset: UUID, filmed: datetime, season: int, number: int, *people: EpisodePerson
) -> Episode:
    return Episode(
        asset_id=asset,
        title="A walk",
        plot="",
        filmed_at=filmed,
        season=season,
        number=number,
        file_stem="unused by Kodi",
        extension=".mov",
        link_target=PurePosixPath(f"/mnt/immich/{asset}.mov"),
        people=people,
        picture_version="hash1",
    )


def show(cover: UUID | None = None) -> Show:
    anna, boris = EpisodePerson(ANNA, "• Анна Сергеевна"), EpisodePerson(BORIS, "• Boris")
    return Show(
        ALBUM,
        "§ Summer",
        "Summer",
        "",
        (
            episode(OTHER, datetime(2023, 6, 10, 9, 0, tzinfo=UTC), 2023, 1, anna),
            episode(ASSET, datetime(2024, 7, 15, 18, 5, 40, tzinfo=UTC), 2024, 1, anna, boris),
        ),
        cover_asset_id=cover,
    )


def test_file_name_has_the_date_and_no_episode_number() -> None:
    stem = kodi_episode_file_stem(datetime(2024, 7, 15, 18, 5, 40), ASSET)
    assert stem == f"2024-07-15 180540 [{int('1e05abcd', 16)}]"
    # A hexadecimal id would hold `e05`, which Kodi takes for episode 5.
    assert not re.search(r"[eE]\d", stem)
    assert not re.search(r"[sS]\d+[eE]\d+|\d+x\d+", stem)


def test_actor_file_name_is_what_kodi_looks_up() -> None:
    assert kodi_actor_file_name("• Анна Сергеевна") == "•_Анна_Сергеевна.jpg"
    assert kodi_actor_file_name('a/b:c "d"') == "a_b_c_d.jpg"


def test_layout() -> None:
    files = KodiLayout().files(show(cover=OTHER), FOLDER)
    by_path = {str(f.path): f for f in files}
    walk = f"{FOLDER}/Season 2024/2024-07-15 180540 [{int('1e05abcd', 16)}]"
    assert sorted(by_path) == sorted(
        [
            f"{FOLDER}/tvshow.nfo",
            f"{FOLDER}/poster.jpg",
            f"{FOLDER}/.actors/•_Анна_Сергеевна.jpg",
            f"{FOLDER}/.actors/•_Boris.jpg",
            f"{FOLDER}/Season 2023/2023-06-10 090000 [{int('da01ae15', 16)}].mov",
            f"{FOLDER}/Season 2023/2023-06-10 090000 [{int('da01ae15', 16)}].nfo",
            f"{FOLDER}/Season 2023/2023-06-10 090000 [{int('da01ae15', 16)}]-thumb.jpg",
            f"{walk}.mov",
            f"{walk}.nfo",
            f"{walk}-thumb.jpg",
        ]
    )
    link = by_path[f"{walk}.mov"]
    assert (link.kind, str(link.link_target)) == (FileKind.LINK, f"/mnt/immich/{ASSET}.mov")
    assert by_path[f"{walk}-thumb.jpg"].image == ImageSource(ASSET, "hash1")
    # A person on several videos has one face per show.
    face = by_path[f"{FOLDER}/.actors/•_Анна_Сергеевна.jpg"]
    assert face.image == ImageSource(ANNA, "face", of_person=True)
    assert b"<season>2024</season>" in (by_path[f"{walk}.nfo"].content or b"")


def test_layout_without_cover_and_people() -> None:
    full = show()
    plain = replace(full, episodes=tuple(replace(e, people=()) for e in full.episodes))
    paths = [str(f.path) for f in KodiLayout().files(plain, FOLDER)]
    assert f"{FOLDER}/poster.jpg" not in paths
    assert not any("/.actors/" in p for p in paths)
