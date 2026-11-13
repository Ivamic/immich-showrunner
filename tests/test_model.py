# SPDX-License-Identifier: AGPL-3.0-or-later
from datetime import UTC, datetime
from pathlib import PurePosixPath
from uuid import UUID

import pytest

from showrunner.config import parse_path_map
from showrunner.immich.models import Album, Asset, ExifInfo, Person
from showrunner.model.naming import (
    episode_file_stem,
    file_extension,
    safe_name,
    season_folder_name,
    show_folder_name,
)
from showrunner.model.paths import map_path
from showrunner.model.show import (
    Options,
    SeasonMode,
    SkipReason,
    build_show,
    split_description,
)

ALBUM_ID = UUID("97769e09-f6ec-4d0b-86d0-3237df31f35b")
OWNER = UUID("7be25f09-c8d5-437a-993a-9cfde9b73b67")
MAPPINGS = parse_path_map("/data=/mnt/immich")
OPTIONS = Options(path_mappings=MAPPINGS, show_prefix="◈ ", person_prefix="◈ ")


def uid(n: int) -> UUID:
    return UUID(f"{n:08x}-0000-4000-8000-000000000000")


def album(name: str = "Family archive", description: str = "") -> Album:
    return Album(
        id=ALBUM_ID,
        album_name=name,
        description=description,
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def video(
    n: int,
    when: str,
    *,
    description: str = "",
    name: str | None = None,
    path: str | None = None,
    **extra: object,
) -> Asset:
    fields: dict[str, object] = {
        "id": uid(n),
        "type": "VIDEO",
        "owner_id": OWNER,
        "original_path": path or f"/data/upload/owner/aa/bb/file{n}.MP4",
        "original_file_name": name or f"VID_{n}.mp4",
        "local_date_time": datetime.fromisoformat(when).replace(tzinfo=UTC),
        "updated_at": datetime(2026, 1, 1, tzinfo=UTC),
        "exif_info": ExifInfo(description=description),
        **extra,
    }
    return Asset.model_validate(fields)


# --- titles -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("description", "title", "plot"),
    [
        ("", None, ""),
        ("   \n ", None, ""),
        ("First steps", "First steps", ""),
        (
            "First steps\nIn the living room.\nWith the cat.",
            "First steps",
            "In the living room.\nWith the cat.",
        ),
        ("First steps\r\n\r\nIn the living room.", "First steps", "In the living room."),
        ("x" * 81, None, "x" * 81),
        ("x" * 80, "x" * 80, ""),
        ("y" * 81 + "\nsecond line", None, "y" * 81 + "\nsecond line"),
    ],
)
def test_split_description(description: str, title: str | None, plot: str) -> None:
    assert split_description(description, 80) == (title, plot)


# --- names ------------------------------------------------------------------------------------


def test_safe_name_removes_what_a_path_can_not_hold() -> None:
    assert safe_name('  a/b\\c:d*e?f"g<h>i|j\x00k\tl  ') == "a b c d e f g h i j k l"
    assert safe_name("..") == "untitled"
    assert safe_name(" . hidden . ") == "hidden"
    assert safe_name("") == "untitled"
    assert "/" not in safe_name("../../etc/passwd")


def test_safe_name_cuts_on_a_character_boundary() -> None:
    name = safe_name("я" * 200, max_bytes=21)
    assert name == "я" * 10
    assert len(name.encode()) <= 21


def test_folder_and_file_names() -> None:
    assert show_folder_name("Summer / lake", ALBUM_ID) == "Summer lake [imm-97769e09]"
    assert season_folder_name(2024) == "Season 2024"
    assert season_folder_name(1) == "Season 01"
    when = datetime(2024, 7, 15, 14, 32, tzinfo=UTC)
    assert episode_file_stem(when, "VID_20240715.mp4", uid(0x712F0482)) == (
        "2024-07-15 VID_20240715 [712f0482]"
    )
    # A name that came from Windows or holds a path does not leak folders into the name.
    assert episode_file_stem(when, "C:\\dir\\clip.final.mov", uid(1)) == (
        "2024-07-15 clip.final [00000001]"
    )


@pytest.mark.parametrize(
    ("path", "extension"),
    [
        ("/a/b.MP4", ".mp4"),
        ("/a/b.tar.mov", ".mov"),
        ("/a/b", ""),
        ("/a/b.toolong1", ""),
        ("/a/.mp4", ""),
    ],
)
def test_file_extension(path: str, extension: str) -> None:
    assert file_extension(path) == extension


# --- paths ------------------------------------------------------------------------------------


def test_map_path() -> None:
    mappings = parse_path_map("/data=/mnt/immich;/data/external=/srv/ext")
    assert map_path("/data/upload/a/b.mp4", mappings) == PurePosixPath("/mnt/immich/upload/a/b.mp4")
    assert map_path("/data/external/trip/c.mp4", mappings) == PurePosixPath("/srv/ext/trip/c.mp4")


@pytest.mark.parametrize(
    "path",
    [
        "/other/a.mp4",  # no mapping
        "/database/a.mp4",  # a prefix of the name, not of the path
        "/data/../etc/passwd",
        "data/upload/a.mp4",
        "/data",
        "",
    ],
)
def test_map_path_refuses(path: str) -> None:
    assert map_path(path, MAPPINGS) is None


# --- shows ------------------------------------------------------------------------------------


def test_episodes_in_order_of_filming_with_seasons_by_year() -> None:
    show = build_show(
        album("Family archive", " Our videos "),
        [
            video(3, "2024-07-15T14:32:00"),
            video(1, "2023-06-10T09:00:00", description="First steps\nIn the living room."),
            video(4, "2024-01-05T12:00:00"),
            video(2, "2023-08-20T15:30:00", description="z" * 100),
        ],
        OPTIONS,
    )
    assert show.title == "◈ Family archive"
    assert show.sort_title == "Family archive"
    assert show.plot == "Our videos"
    assert show.seasons == (2023, 2024)
    assert [(e.season, e.number, e.title) for e in show.episodes] == [
        (2023, 1, "First steps"),
        (2023, 2, "2023-08-20 15:30"),
        (2024, 1, "2024-01-05 12:00"),
        (2024, 2, "2024-07-15 14:32"),
    ]
    first = show.episodes[0]
    assert first.plot == "In the living room."
    assert first.file_stem == "2023-06-10 VID_1 [00000001]"
    assert first.extension == ".mp4"
    assert first.link_target == PurePosixPath("/mnt/immich/upload/owner/aa/bb/file1.MP4")
    assert show.episodes[1].plot == "z" * 100


def test_inserting_a_video_shifts_numbers_but_not_file_names() -> None:
    before = [video(1, "2024-01-05T12:00:00"), video(2, "2024-07-15T14:32:00")]
    after = [*before, video(3, "2024-03-08T10:00:00")]
    old = {e.asset_id: e for e in build_show(album(), before, OPTIONS).episodes}
    new = {e.asset_id: e for e in build_show(album(), after, OPTIONS).episodes}
    assert (old[uid(2)].number, new[uid(2)].number) == (2, 3)
    assert new[uid(3)].number == 2
    assert old[uid(2)].file_stem == new[uid(2)].file_stem


def test_renaming_changes_only_the_title() -> None:
    assets = [video(1, "2024-01-05T12:00:00")]
    a = build_show(album("Old name"), assets, OPTIONS)
    b = build_show(album("New name"), assets, OPTIONS)
    assert a.title != b.title
    assert a.episodes == b.episodes


def test_single_season() -> None:
    options = Options(path_mappings=MAPPINGS, season_mode=SeasonMode.SINGLE)
    show = build_show(
        album(), [video(2, "2024-01-05T12:00:00"), video(1, "2023-06-10T09:00:00")], options
    )
    assert [(e.season, e.number) for e in show.episodes] == [(1, 1), (1, 2)]
    assert show.title == "Family archive"


def test_same_moment_is_ordered_by_id_and_duplicates_are_dropped() -> None:
    assets = [
        video(2, "2024-01-05T12:00:00"),
        video(1, "2024-01-05T12:00:00"),
        video(2, "2024-01-05T12:00:00"),
    ]
    show = build_show(album(), assets, OPTIONS)
    assert [e.asset_id for e in show.episodes] == [uid(1), uid(2)]


def test_skipped_videos() -> None:
    show = build_show(
        album(),
        [
            video(1, "2024-01-01T00:00:00", type="IMAGE"),
            video(2, "2024-01-01T00:00:00", is_trashed=True),
            video(3, "2024-01-01T00:00:00", is_offline=True),
            video(4, "2024-01-01T00:00:00", visibility="locked"),
            video(5, "2024-01-01T00:00:00", path="/elsewhere/a.mp4"),
            video(6, "2024-01-01T00:00:00", path="/data/upload/noext"),
            video(7, "2024-01-01T00:00:00", visibility="archive"),
        ],
        OPTIONS,
    )
    assert [e.asset_id for e in show.episodes] == [uid(7)]
    assert [s.reason for s in show.skipped] == [
        SkipReason.NOT_A_VIDEO,
        SkipReason.TRASHED,
        SkipReason.OFFLINE,
        SkipReason.HIDDEN,
        SkipReason.NO_PATH_MAPPING,
        SkipReason.NO_EXTENSION,
    ]


def test_people_named_only_with_prefix_once() -> None:
    anna, nobody = uid(100), uid(101)
    asset = video(
        1,
        "2024-01-01T00:00:00",
        people=[
            Person(id=anna, name="Anna"),
            Person(id=nobody, name=" "),
            Person(id=anna, name="Anna"),
        ],
    )
    show = build_show(album(), [asset], OPTIONS)
    assert [(p.id, p.name) for p in show.episodes[0].people] == [(anna, "◈ Anna")]


def test_album_without_a_name() -> None:
    assert build_show(album("  "), [], OPTIONS).title == "◈ Untitled album"
