# SPDX-License-Identifier: AGPL-3.0-or-later
"""Slideshows in the sync: episodes of Season 0 placed after their year, files that keep their
names, drawn only when their cut list changes, the newest years first within the time of a pass,
the drawn file written by the executor like any file of the app; an album of photos only becomes a
show of slideshows only."""

import hashlib
import os
from datetime import date, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from test_slideshow_photos import FakeSlideshow, jpeg, scene

from fake_immich import FakeImmich, album_id
from showrunner.config import parse_path_map
from showrunner.immich.client import ImmichClient
from showrunner.model.show import Options, Show, Special
from showrunner.slideshow.plan import Clip
from showrunner.slideshow.score import Track
from showrunner.store.registry import Registry
from showrunner.sync.executor import Executor, Result
from showrunner.sync.plan import Action, ActionType, Entry
from showrunner.sync.service import Output, sync_outputs
from showrunner.sync.specials import SpecialsContext, specials_of
from showrunner.targets.base import DesiredFile, FileKind, VideoSource
from showrunner.targets.jellyfin.layout import JellyfinLayout
from showrunner.targets.kodi.layout import KodiLayout
from showrunner.targets.nfo import special_nfo

OPTIONS = Options(path_mappings=parse_path_map("/data=/mnt/immich"), show_prefix="◈ ")
needs_links = pytest.mark.skipif(os.name == "nt", reason="symbolic links need Linux")


def clip(year: int, part: int = 0) -> Clip:
    return Clip(
        album_id=album_id(1),
        year=year,
        part=part,
        first=datetime(year, 7, 1),
        last=datetime(year, 8, 1),
        shots=(),
        left_out=0,
        title="Trip",
        credits=True,
        music_credits=("“Piece” by Someone, CC BY 4.0",),
    )


def show(seasons: tuple[int, ...]) -> Show:
    from showrunner.model.show import Episode

    episodes = tuple(
        Episode(
            asset_id=album_id(100 + s),
            title="v",
            plot="",
            filmed_at=datetime(s, 1, 1) if s > 1000 else datetime(2024, 1, 1),
            season=s,
            number=1,
            file_stem=f"v{s}",
            extension=".mp4",
            link_target=PurePosixPath(f"/mnt/immich/v{s}.mp4"),
        )
        for s in seasons
    )
    return Show(album_id(1), "◈ Trip", "Trip", "", episodes)


# --- episodes and files -----------------------------------------------------------------------


def test_slideshows_are_episodes_of_season_0_after_their_year() -> None:
    made = specials_of(show((2023, 2024)), [clip(2024, 2), clip(2023), clip(2024, 1)], "film")
    assert [(s.year, s.part, s.number) for s in made] == [(2023, 0, 1), (2024, 1, 2), (2024, 2, 3)]
    assert [s.title for s in made] == ["Photos 2023", "Photos 2024 (1/2)", "Photos 2024 (2/2)"]
    assert [s.after_season for s in made] == [2023, 2024, 2024]
    assert made[0].plot == "Music: “Piece” by Someone, CC BY 4.0"
    assert made[0].aired == date(2023, 12, 31)
    assert made[0].version.endswith("-film"), "another style: drawn again"


def test_a_year_without_its_season_follows_the_season_before_or_none() -> None:
    assert specials_of(show((2022,)), [clip(2024)], "s")[0].after_season == 2022
    assert specials_of(show((2025,)), [clip(2024)], "s")[0].after_season is None
    assert specials_of(show((1,)), [clip(2024)], "s")[0].after_season == 1, "one season"
    assert specials_of(show(()), [clip(2024)], "s")[0].after_season is None, "photos only"


def test_the_nfo_places_a_slideshow_for_both_media_servers() -> None:
    (special,) = specials_of(show((2024,)), [clip(2024)], "s")
    text = special_nfo(album_id(1), special).decode()
    for tag in (
        "<season>0</season>",
        "<episode>1</episode>",
        "<airsafter_season>2024</airsafter_season>",
        "<displayseason>2024</displayseason>",
        "<displayepisode>4096</displayepisode>",
        "<title>Photos 2024</title>",
    ):
        assert tag in text, tag
    assert f"{album_id(1)}/2024/0" in text


def test_the_files_of_a_slideshow_keep_their_names() -> None:
    (special,) = specials_of(show((2024,)), [clip(2024)], "s")
    with_special = Show(album_id(1), "◈ Trip", "Trip", "", (), specials=(special,))
    jellyfin = {str(f.path): f for f in JellyfinLayout().files(with_special, "Trip")}
    kodi = {str(f.path): f for f in KodiLayout().files(with_special, "Trip")}
    video = jellyfin["Trip/Specials/20241231-235900 Photos 2024 [slideshow 2024 0].mp4"]
    assert video.kind is FileKind.VIDEO and video.source_version == special.version
    assert "Trip/Specials/20241231-235900 Photos 2024 [slideshow 2024 0].nfo" in jellyfin
    assert "Trip/Specials/2024-12-31 235900 [202400].mp4" in kodi
    assert "e" not in ["2024-12-31 235900 ", "202400]"][1], "Kodi reads e+digits"


# --- the executor -----------------------------------------------------------------------------


def video_file(tmp_path: Path, content: bytes, version: str = "v1") -> DesiredFile:
    drawn = tmp_path / f"drawn-{version}.mp4"
    drawn.write_bytes(content)
    special = Special(2024, 0, 1, 1, "Photos 2024", "", date(2024, 12, 31), None, version, None)
    return DesiredFile(
        path=PurePosixPath("Trip/Specials/s.mp4"),
        kind=FileKind.VIDEO,
        album_id=album_id(1),
        video=VideoSource(album_id(1), special),
        drawn=drawn,
        drawn_hash=hashlib.sha256(content).hexdigest(),
    )


def entry_of(file: DesiredFile) -> Entry:
    return Entry(
        file.path, file.kind, file.album_id, content_hash=file.content_hash, source_version="v1"
    )


def test_a_slideshow_is_written_replaced_and_removed_only_as_the_app_wrote_it(
    tmp_path: Path,
) -> None:
    out = tmp_path / "out"
    out.mkdir()
    executor = Executor(out, [PurePosixPath("/mnt/immich")])
    first = video_file(tmp_path, b"first slideshow")
    done = executor.apply(Action(ActionType.CREATE, first.path, first.kind, first.album_id, first))
    assert done.result is Result.DONE
    assert (out / first.path).read_bytes() == b"first slideshow"
    assert first.drawn is not None and first.drawn.exists(), "copied: another output takes it too"

    second = video_file(tmp_path, b"second slideshow", "v2")
    action = Action(ActionType.REPLACE, first.path, FileKind.VIDEO, first.album_id, second)
    replaced = executor.apply(Action(**{**action.__dict__, "entry": entry_of(first)}))
    assert replaced.result is Result.DONE
    assert (out / first.path).read_bytes() == b"second slideshow"

    # Somebody changed the file: it is not the app's any more.
    (out / first.path).write_bytes(b"edited by hand")
    gone = Action(
        ActionType.REMOVE, first.path, FileKind.VIDEO, first.album_id, None, entry_of(second)
    )
    assert executor.apply(gone).result is Result.FOREIGN
    assert (out / first.path).exists()


# --- a whole pass -----------------------------------------------------------------------------


class FakeSpecials(SpecialsContext):
    """Draws a slideshow as a few bytes naming its version, in no time; counts what it draws."""

    def __init__(self, data_dir: Path, *, budget: float = 600.0) -> None:
        super().__init__(
            data_dir=data_dir,
            full=True,
            styles=["film"],
            budget_seconds=budget,
            worker=None,  # type: ignore[arg-type]
            clock=lambda: 0.0,
        )
        self.made: list[str] = []

    async def music(self) -> list[Track]:
        return []

    async def draw(self, immich: ImmichClient, special: Special) -> tuple[Path, str]:
        if self.drawn(special.version):
            return self._drawn[special.version]
        self.made.append(f"{special.year}-{special.part}")
        self.work.mkdir(parents=True, exist_ok=True)
        path = self.work / f"{special.version}.mp4"
        content = f"SLIDESHOW {special.title} {special.version}".encode()
        path.write_bytes(content)
        self._drawn[special.version] = (path, hashlib.sha256(content).hexdigest())
        return self._drawn[special.version]


def photo_album(immich: FakeImmich | None = None, years: tuple[int, ...] = (2023,)) -> FakeImmich:
    immich = immich or FakeImmich()
    album = immich.add_album(1, "Holidays")
    n = 10
    for year in years:
        for i in range(7):
            when = datetime(year, 7, 1, 9) + timedelta(minutes=30 * i)
            immich.add_photo(album, n, f"{when:%Y-%m-%dT%H:%M:%S}", jpeg(scene(seed=n)))
            n += 1
    return immich


async def one_pass(
    immich: FakeImmich, session: AsyncSession, out: Path, specials: FakeSpecials, **kw: Any
) -> Any:
    async with immich.client() as client:
        (report,) = await sync_outputs(
            immich=client,
            registry=Registry(session),
            outputs=[Output(JellyfinLayout(), Executor(out, [PurePosixPath("/mnt/immich")]))],
            options=OPTIONS,
            full=kw.get("full", False),
            slideshow=FakeSlideshow(),
            specials=specials,
        )
    return report


def specials_in(out: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in out.rglob("Specials/*") if not p.name.startswith(".")}


@pytest.mark.anyio
async def test_an_album_of_photos_becomes_a_show_of_slideshows(
    session: AsyncSession, tmp_path: Path
) -> None:
    immich = photo_album(years=(2023, 2024))
    out, data = tmp_path / "out", tmp_path / "data"
    out.mkdir()
    specials = FakeSpecials(data)
    report = await one_pass(immich, session, out, specials)
    assert report.ok
    files = specials_in(out)
    assert sorted(n for n in files if n.endswith(".mp4")) == [
        "20231231-235900 Photos 2023 [slideshow 2023 0].mp4",
        "20241231-235900 Photos 2024 [slideshow 2024 0].mp4",
    ]
    assert specials.made == ["2024-0", "2023-0"], "the newest year first"
    assert (out / "Holidays [imm-00000001]" / "tvshow.nfo").exists()
    assert not list(data.glob("slideshows/*.mp4")), "nothing drawn is kept (D-101)"

    # Nothing changed: nothing is drawn again.
    again = FakeSpecials(data)
    await one_pass(immich, session, out, again, full=True)
    assert again.made == []


@pytest.mark.anyio
async def test_a_new_photo_draws_its_year_again_under_the_same_name(
    session: AsyncSession, tmp_path: Path
) -> None:
    immich = photo_album(years=(2023, 2024))
    out, data = tmp_path / "out", tmp_path / "data"
    out.mkdir()
    await one_pass(immich, session, out, FakeSpecials(data))
    before = specials_in(out)
    album = next(iter(immich.albums))
    immich.add_photo(album, 99, "2024-07-02T12:00:00", jpeg(scene(seed=99)))
    immich.touch(album, "2026-02-01T00:00:00.000Z")
    later = FakeSpecials(data)
    await one_pass(immich, session, out, later)
    assert later.made == ["2024-0"]
    after = specials_in(out)
    assert after.keys() == before.keys()
    name = "20241231-235900 Photos 2024 [slideshow 2024 0].mp4"
    assert after[name] != before[name]


@pytest.mark.anyio
async def test_what_the_time_does_not_allow_waits_for_the_next_pass(
    session: AsyncSession, tmp_path: Path
) -> None:
    immich = photo_album(years=(2023,))
    out, data = tmp_path / "out", tmp_path / "data"
    out.mkdir()
    report = await one_pass(immich, session, out, FakeSpecials(data, budget=0))
    assert report.slideshows_waiting == 1
    assert specials_in(out) == {}, "neither the slideshow nor its NFO"
    # Not stamped: the next quick pass reads the album again and draws it.
    later = FakeSpecials(data)
    await one_pass(immich, session, out, later)
    assert later.made == ["2023-0"]
    assert len(specials_in(out)) == 2


@pytest.mark.anyio
async def test_a_year_with_too_few_photos_gets_no_slideshow(
    session: AsyncSession, tmp_path: Path
) -> None:
    immich = FakeImmich()
    album = immich.add_album(1, "Few")
    for i in range(3):
        immich.add_photo(album, 10 + i, f"2023-07-01T1{i}:00:00", jpeg(scene(seed=i)))
    out = tmp_path / "out"
    out.mkdir()
    specials = FakeSpecials(tmp_path / "data")
    await one_pass(immich, session, out, specials)
    assert specials.made == [] and specials_in(out) == {}
