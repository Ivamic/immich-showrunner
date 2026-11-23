# SPDX-License-Identifier: AGPL-3.0-or-later
"""Slideshows in the sync: episodes of Season 0 placed after their year, files that keep their
names, drawn only when their cut list changes, the newest years first within the time of a pass,
the drawn file written by the executor like any file of the app; an album of photos only becomes a
show of slideshows only."""

import hashlib
import json
import os
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from test_slideshow_photos import FakeSlideshow, jpeg, scene

from fake_immich import FakeImmich, album_id, asset_id
from showrunner.config import parse_path_map
from showrunner.immich.client import ImmichClient
from showrunner.model.naming import WHOLE_ALBUM, special_file_stem
from showrunner.model.show import Options, SeasonMode, Show, Special
from showrunner.slideshow.plan import Clip
from showrunner.slideshow.score import Track
from showrunner.store.registry import Registry
from showrunner.sync.executor import Executor, Result
from showrunner.sync.plan import Action, ActionType, Entry
from showrunner.sync.service import Output, sync_outputs
from showrunner.sync.specials import SpecialsContext, plan_file, specials_of
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


def test_an_album_of_one_season_has_slideshows_of_all_its_years() -> None:
    def whole(part: int, first: int, last: int) -> Clip:
        return replace(
            clip(WHOLE_ALBUM, part), first=datetime(first, 3, 1), last=datetime(last, 9, 30)
        )

    made = specials_of(show((1,)), [whole(1, 2019, 2021), whole(2, 2022, 2024)], "s")
    span = "2019\N{EN DASH}2024"
    assert [s.title for s in made] == [f"Photos {span} (1/2)", f"Photos {span} (2/2)"]
    assert [s.after_season for s in made] == [1, 1]
    assert made[1].aired == date(2024, 9, 30), "the day of its last photo"
    (alone,) = specials_of(show((1,)), [whole(0, 2024, 2024)], "s")
    assert alone.title == "Photos 2024"
    assert special_file_stem(WHOLE_ALBUM, 1) == "99991231-235901 Photos [slideshow all 1]"


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
        self.clips: list[Clip] = []
        self.queues: list[int] = []
        self.while_drawing: Callable[[], Awaitable[None]] | None = None

    async def music(self) -> list[Track]:
        return []

    async def draw(
        self, immich: ImmichClient, special: Special, album_id: UUID | None = None, queue: int = 0
    ) -> tuple[Path, str]:
        self.queues.append(queue)
        if self.while_drawing is not None:
            await self.while_drawing()
        if self.drawn(special.version):
            return self._drawn[special.version]
        self.made.append(f"{special.year}-{special.part}")
        self.clips.append(special.clip)
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
    immich: FakeImmich, session: AsyncSession, out: Path, specials: SpecialsContext, **kw: Any
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
async def test_one_season_makes_one_slideshow_of_the_whole_album(
    session: AsyncSession, tmp_path: Path
) -> None:
    out, data = tmp_path / "out", tmp_path / "data"
    out.mkdir()
    immich = photo_album(years=(2023, 2024))
    assert (await one_pass(immich, session, out, FakeSpecials(data))).ok
    assert len([n for n in specials_in(out) if n.endswith(".mp4")]) == 2, "by year"

    # One season, chosen on the page: the years together, the slideshows by year go.
    registry = Registry(session)
    row = (await registry.shows())[album_id(1)]
    row.season_mode = SeasonMode.SINGLE.value
    await registry.commit()
    report = await one_pass(immich, session, out, FakeSpecials(data), full=True)
    assert report.ok
    files = specials_in(out)
    assert sorted(n for n in files if n.endswith(".mp4")) == [
        "99991231-235900 Photos [slideshow all 0].mp4"
    ]
    nfo = files["99991231-235900 Photos [slideshow all 0].nfo"].decode()
    assert "<title>Photos 2023\N{EN DASH}2024</title>" in nfo


@pytest.mark.anyio
async def test_the_page_can_save_a_choice_while_a_slideshow_is_drawn(
    session: AsyncSession, engine: AsyncEngine, tmp_path: Path
) -> None:
    out, data = tmp_path / "out", tmp_path / "data"
    out.mkdir()
    specials = FakeSpecials(data)
    saved = []

    async def save_a_choice() -> None:
        async with engine.connect() as other:
            await other.execute(text("SET lock_timeout = '2s'"))
            result = await other.execute(text("UPDATE album_slideshow SET music_seed = music_seed"))
            saved.append(result.rowcount)
            await other.rollback()

    specials.while_drawing = save_a_choice
    assert (await one_pass(photo_album(years=(2024,)), session, out, specials)).ok
    assert saved == [1], "the plan is kept before drawing, nothing waits for the drawing"


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
    assert specials.queues == [1, 0], "the page sees how many wait"
    kept = json.loads(plan_file(data, album_id(1)).read_text(encoding="utf-8"))
    assert [(s["year"], s["part"]) for s in kept["slideshows"]] == [(2023, 0), (2024, 0)]
    assert {p["fate"] for s in kept["slideshows"] for p in s["photos"]} == {"shown"}
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
async def test_the_title_names_the_places_unless_the_album_says_no(
    session: AsyncSession, tmp_path: Path
) -> None:
    immich = photo_album(years=(2024,))
    album = next(iter(immich.albums))
    for i, item in enumerate(immich.photos[album]):
        item["exifInfo"] |= {"city": "Nice" if i < 4 else "Monaco", "country": "France"}
    out, data = tmp_path / "out", tmp_path / "data"
    out.mkdir()
    first = FakeSpecials(data)
    await one_pass(immich, session, out, first)
    assert [c.places for c in first.clips] == [("Nice", "Monaco")]

    # Switched off for this album on the page: drawn again without them.
    await Registry(session).save_album_slideshow(album_id(1), places=False)
    await Registry(session).commit()
    second = FakeSpecials(data)
    await one_pass(immich, session, out, second, full=True)
    assert second.made == ["2024-0"]
    assert [c.places for c in second.clips] == [()]

    # Switched off for all, on again for this album; the text in German.
    third = FakeSpecials(data)
    third.places, third.language = False, "de"
    await Registry(session).save_album_slideshow(album_id(1), places=True)
    await Registry(session).commit()
    await one_pass(immich, session, out, third, full=True)
    assert [(c.places, c.language) for c in third.clips] == [(("Nice", "Monaco"), "de")]


class RecordingWorker:
    """Draws nothing: keeps the pictures a slideshow was to be drawn from."""

    def __init__(self) -> None:
        self.pictures: list[dict[str, bytes]] = []

    async def run(self, task: Any, clip: Any, photos: dict[str, str], *rest: Any) -> None:
        self.pictures.append({k: Path(v).read_bytes() for k, v in photos.items()})
        Path(rest[1]).write_bytes(b"SLIDESHOW")


class DrawingSpecials(SpecialsContext):
    """The real drawing, but by RecordingWorker and without music."""

    def __init__(self, data_dir: Path, worker: RecordingWorker) -> None:
        super().__init__(
            data_dir=data_dir,
            full=True,
            styles=["film"],
            worker=worker,  # type: ignore[arg-type]
            clock=lambda: 0.0,
        )

    async def music(self) -> list[Track]:
        return []


@pytest.mark.anyio
async def test_a_photo_edited_in_immich_draws_its_slideshow_again_as_edited(
    session: AsyncSession, tmp_path: Path
) -> None:
    immich = photo_album(years=(2023,))
    out, data = tmp_path / "out", tmp_path / "data"
    out.mkdir()
    worker = RecordingWorker()
    await one_pass(immich, session, out, DrawingSpecials(data, worker))
    (first,) = worker.pictures
    key = str(asset_id(10))
    assert first[key] == immich.photo_files[key]

    # Turned in Immich: drawn again, from the edited picture.
    album = next(iter(immich.albums))
    turned = jpeg(scene(seed=10).rotate(180))
    immich.edit_photo(album, 10, turned, thumbhash="turned")
    immich.touch(album, "2026-02-01T00:00:00.000Z")
    await one_pass(immich, session, out, DrawingSpecials(data, worker))
    assert len(worker.pictures) == 2, "drawn again"
    assert worker.pictures[1][key] == turned, "from the edited photo"
    other = str(asset_id(11))
    assert worker.pictures[1][other] == immich.photo_files[other], "the others as they were"


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


# --- the folder of slideshows (D-102) -------------------------------------------------------


async def store_pass(
    immich: FakeImmich, session: AsyncSession, tmp_path: Path, specials: FakeSpecials
) -> list[Any]:
    from showrunner.targets.specials import SlideshowStore

    store, out = tmp_path / "store", tmp_path / "out"
    store.mkdir(exist_ok=True)
    out.mkdir(exist_ok=True)
    media = PurePosixPath("/media/slideshows")
    roots = [PurePosixPath("/mnt/immich"), media]
    async with immich.client() as client:
        return await sync_outputs(
            immich=client,
            registry=Registry(session),
            outputs=[
                Output(JellyfinLayout(media), Executor(out, roots), notify=True),
                Output(SlideshowStore(), Executor(store, [])),
            ],
            options=OPTIONS,
            full=False,
            slideshow=FakeSlideshow(),
            specials=specials,
        )


@needs_links
@pytest.mark.anyio
async def test_slideshows_lie_in_their_folder_and_the_outputs_link_to_them(
    session: AsyncSession, tmp_path: Path
) -> None:
    immich = photo_album(years=(2023,))
    specials = FakeSpecials(tmp_path / "data")
    reports = await store_pass(immich, session, tmp_path, specials)
    assert [r.target for r in reports] == ["slideshows", "jellyfin"], "the folder first"
    name = "20231231-235900 Photos 2023 [slideshow 2023 0]"
    stored = tmp_path / "store" / "Holidays [imm-00000001]" / f"{name}.mp4"
    assert stored.read_bytes().startswith(b"SLIDESHOW")
    link = tmp_path / "out" / "Holidays [imm-00000001]" / "Specials" / f"{name}.mp4"
    assert link.is_symlink()
    assert os.readlink(link) == f"/media/slideshows/Holidays [imm-00000001]/{name}.mp4"
    assert link.with_suffix(".nfo").exists()
    assert specials.made == ["2023-0"], "drawn once, for the folder"


@needs_links
@pytest.mark.anyio
async def test_no_link_to_a_slideshow_not_drawn_yet(session: AsyncSession, tmp_path: Path) -> None:
    immich = photo_album(years=(2023,))
    await store_pass(immich, session, tmp_path, FakeSpecials(tmp_path / "data", budget=0))
    assert not list((tmp_path / "out").rglob("Specials/*"))
    assert not list((tmp_path / "store").rglob("*.mp4"))
    await store_pass(immich, session, tmp_path, FakeSpecials(tmp_path / "data"))
    assert len(list((tmp_path / "out").rglob("Specials/*"))) == 2


@needs_links
@pytest.mark.anyio
async def test_a_slideshow_drawn_again_tells_the_media_server(
    session: AsyncSession, tmp_path: Path
) -> None:
    immich = photo_album(years=(2023,))
    await store_pass(immich, session, tmp_path, FakeSpecials(tmp_path / "data"))
    registry = Registry(session)
    await registry.clear_pending(await registry.pending("jellyfin"), "jellyfin")
    await session.commit()
    album = next(iter(immich.albums))
    immich.add_photo(album, 98, "2023-07-01T14:00:00", jpeg(scene(seed=98)))
    immich.touch(album, "2026-02-01T00:00:00.000Z")
    reports = await store_pass(immich, session, tmp_path, FakeSpecials(tmp_path / "data"))
    store, jellyfin = reports
    assert store.replaced == 1
    assert jellyfin.plan.of_type(ActionType.REPLACE) == (), "the link did not change"
    assert album in jellyfin.changed_folders
    assert album in await registry.pending("jellyfin")


@needs_links
def test_a_copy_gives_way_to_a_link_and_back(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    executor = Executor(out, [PurePosixPath("/media/slideshows")])
    copy = video_file(tmp_path, b"a copy")
    executor.apply(Action(ActionType.CREATE, copy.path, copy.kind, copy.album_id, copy))
    link = DesiredFile(
        path=copy.path,
        kind=FileKind.LINK,
        album_id=copy.album_id,
        link_target=PurePosixPath("/media/slideshows/Trip/s.mp4"),
        video=copy.video,
    )
    to_link = Action(
        ActionType.REPLACE, copy.path, FileKind.LINK, copy.album_id, link, entry_of(copy)
    )
    assert executor.apply(to_link).result is Result.DONE
    assert (out / copy.path).is_symlink()
    back = video_file(tmp_path, b"a copy again", "v2")
    link_entry = Entry(link.path, FileKind.LINK, link.album_id, link_target=link.link_target)
    to_file = Action(ActionType.REPLACE, copy.path, FileKind.VIDEO, copy.album_id, back, link_entry)
    assert executor.apply(to_file).result is Result.DONE
    assert (out / copy.path).read_bytes() == b"a copy again"
    # A file somebody else put there is never taken for ours.
    (out / copy.path).write_bytes(b"by hand")
    stale = Action(
        ActionType.REPLACE, copy.path, FileKind.LINK, copy.album_id, link, entry_of(back)
    )
    assert executor.apply(stale).result is Result.FOREIGN


# --- the trash (D-105) ------------------------------------------------------------------------


def test_a_slideshow_drawn_again_or_removed_goes_to_the_trash(tmp_path: Path) -> None:
    from showrunner.sync.executor import empty_trash

    out, trash = tmp_path / "store", tmp_path / "store" / ".trash"
    out.mkdir()
    executor = Executor(out, [], trash, 90)
    first = video_file(tmp_path, b"first slideshow")
    executor.apply(Action(ActionType.CREATE, first.path, first.kind, first.album_id, first))
    second = video_file(tmp_path, b"second slideshow", "v2")
    executor.apply(
        Action(
            ActionType.REPLACE, first.path, FileKind.VIDEO, first.album_id, second, entry_of(first)
        )
    )
    assert (out / first.path).read_bytes() == b"second slideshow"
    (kept,) = (trash / "Trip").iterdir()
    assert kept.read_bytes() == b"first slideshow" and kept.name.startswith("s (until ")
    gone = Action(
        ActionType.REMOVE, first.path, FileKind.VIDEO, first.album_id, None, entry_of(second)
    )
    assert executor.apply(gone).result is Result.DONE
    assert not (out / first.path).exists()
    assert sorted(p.read_bytes() for p in (trash / "Trip").iterdir()) == [
        b"first slideshow",
        b"second slideshow",
    ]
    # 90 days on, the trash empties itself; a younger file stays.
    old, young = sorted((trash / "Trip").iterdir())
    os.utime(old, (0, 0))
    assert empty_trash(trash, 90) == 1
    assert list((trash / "Trip").iterdir()) == [young]


def test_without_a_trash_a_slideshow_is_removed(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    executor = Executor(out, [])
    first = video_file(tmp_path, b"first slideshow")
    executor.apply(Action(ActionType.CREATE, first.path, first.kind, first.album_id, first))
    gone = Action(
        ActionType.REMOVE, first.path, FileKind.VIDEO, first.album_id, None, entry_of(first)
    )
    executor.apply(gone)
    assert not any(p.is_file() for p in tmp_path.rglob("*.mp4") if "out" in p.parts)
