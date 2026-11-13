# SPDX-License-Identifier: AGPL-3.0-or-later
from datetime import UTC, datetime
from pathlib import PurePosixPath
from uuid import UUID
from xml.etree import ElementTree as ET

import pytest

from showrunner.model.show import Episode, EpisodePerson, Show
from showrunner.targets.base import DesiredFile, FileKind
from showrunner.targets.jellyfin.layout import JellyfinLayout
from showrunner.targets.jellyfin.nfo import episode_nfo, show_nfo

ALBUM = UUID("97769e09-f6ec-4d0b-86d0-3237df31f35b")
ASSET = UUID("712f0482-ba03-4739-a060-cea85f44e17d")
ANNA = UUID("8800ba4a-52a0-4f68-944a-6587ea5ff3c2")


def episode(**changes: object) -> Episode:
    values: dict[str, object] = {
        "asset_id": ASSET,
        "title": "First <steps> & more",
        "plot": "In the living room.\nWith the cat.",
        "filmed_at": datetime(2024, 7, 15, 14, 32, tzinfo=UTC),
        "season": 2024,
        "number": 3,
        "file_stem": "2024-07-15 VID_D [712f0482]",
        "extension": ".mp4",
        "link_target": PurePosixPath("/mnt/immich/upload/a/b/c.mp4"),
        "people": (EpisodePerson(ANNA, "◈ Анна"),),
    }
    values.update(changes)
    return Episode(**values)  # type: ignore[arg-type]


def show(*episodes: Episode) -> Show:
    return Show(ALBUM, "◈ Дача и лето", "Дача и лето", "Our summers", tuple(episodes))


def test_show_nfo() -> None:
    data = show_nfo(show())
    assert data.startswith(b'<?xml version="1.0" encoding="utf-8" standalone="yes"?>\n<tvshow>')
    root = ET.fromstring(data)
    assert root.findtext("title") == "◈ Дача и лето"
    assert root.findtext("sorttitle") == "Дача и лето"
    assert root.findtext("plot") == "Our summers"
    unique = root.find("uniqueid")
    assert unique is not None
    assert (unique.text, unique.get("type")) == (str(ALBUM), "immich")


def test_episode_nfo() -> None:
    root = ET.fromstring(episode_nfo(episode()))
    assert root.tag == "episodedetails"
    assert root.findtext("title") == "First <steps> & more"
    assert root.findtext("plot") == "In the living room.\nWith the cat."
    assert root.findtext("aired") == "2024-07-15"
    assert (root.findtext("season"), root.findtext("episode")) == ("2024", "3")
    assert root.findtext("uniqueid") == str(ASSET)
    assert [(a.findtext("name"), a.findtext("type")) for a in root.findall("actor")] == [
        ("◈ Анна", "Actor")
    ]


def test_nfo_without_plot_and_with_control_characters() -> None:
    data = episode_nfo(episode(title="bad\x00\x0btitle", plot="", people=()))
    root = ET.fromstring(data)
    assert root.findtext("title") == "badtitle"
    assert root.find("plot") is None
    assert root.find("actor") is None


def test_nfo_is_the_same_on_every_run() -> None:
    assert episode_nfo(episode()) == episode_nfo(episode())


def test_layout() -> None:
    other = UUID("00000001-0000-4000-8000-000000000000")
    files = JellyfinLayout().files(
        show(
            episode(),
            episode(asset_id=other, season=2023, number=1, file_stem="2023-06-10 VID_A [00000001]"),
        ),
        "Summer [imm-97769e09]",
    )
    assert [(str(f.path), f.kind) for f in files] == [
        ("Summer [imm-97769e09]/tvshow.nfo", FileKind.SHOW_NFO),
        ("Summer [imm-97769e09]/Season 2024/2024-07-15 VID_D [712f0482].mp4", FileKind.LINK),
        ("Summer [imm-97769e09]/Season 2024/2024-07-15 VID_D [712f0482].nfo", FileKind.EPISODE_NFO),
        ("Summer [imm-97769e09]/Season 2023/2023-06-10 VID_A [00000001].mp4", FileKind.LINK),
        ("Summer [imm-97769e09]/Season 2023/2023-06-10 VID_A [00000001].nfo", FileKind.EPISODE_NFO),
    ]
    link = files[1]
    assert link.link_target == PurePosixPath("/mnt/immich/upload/a/b/c.mp4")
    assert link.content is None and link.content_hash is None
    assert link.asset_id == ASSET
    assert files[0].asset_id is None and files[0].content_hash is not None
    assert all(f.album_id == ALBUM for f in files)


@pytest.mark.parametrize("path", ["/abs/a.nfo", "a/../../b.nfo", "."])
def test_desired_file_must_stay_inside_the_output_folder(path: str) -> None:
    with pytest.raises(ValueError):
        DesiredFile(PurePosixPath(path), FileKind.SHOW_NFO, ALBUM, content=b"x")


def test_desired_file_is_either_a_link_or_has_content() -> None:
    path = PurePosixPath("a/b.mp4")
    with pytest.raises(ValueError):
        DesiredFile(path, FileKind.LINK, ALBUM)
    with pytest.raises(ValueError):
        DesiredFile(path, FileKind.LINK, ALBUM, link_target=PurePosixPath("relative/x.mp4"))
    with pytest.raises(ValueError):
        DesiredFile(path, FileKind.EPISODE_NFO, ALBUM)
    with pytest.raises(ValueError):
        DesiredFile(
            path, FileKind.EPISODE_NFO, ALBUM, content=b"x", link_target=PurePosixPath("/x")
        )
