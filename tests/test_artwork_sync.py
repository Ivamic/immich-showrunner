# SPDX-License-Identifier: AGPL-3.0-or-later
"""Artwork in the sync: frames are looked at once and kept, pictures are planned from them and
drawn only when their plan changes; without artwork the poster is the album's cover."""

import os
import random
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import UUID

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from fake_immich import FakeImmich, asset_id
from showrunner.artwork.jobs import ArtworkJob, choose_style, plan_show
from showrunner.artwork.quality import Quality
from showrunner.artwork.select import LOOK_VERSION, FrameLook
from showrunner.artwork.style import OutputKind, builtin_styles
from showrunner.config import parse_path_map
from showrunner.immich.models import Album, Asset
from showrunner.model.show import Options, Show, build_show
from showrunner.store.models import Base
from showrunner.store.registry import Registry
from showrunner.sync import artwork as artwork_step
from showrunner.sync.artwork import ArtworkContext
from showrunner.sync.executor import MARKER_NAME, Executor
from showrunner.sync.service import Output, sync_outputs
from showrunner.targets.artwork import picture_files
from showrunner.targets.base import FileKind
from showrunner.targets.jellyfin.layout import PICTURE_NAMES, JellyfinLayout

pytestmark = pytest.mark.anyio
needs_links = pytest.mark.skipif(os.name == "nt", reason="symbolic links need Linux")

OPTIONS = Options(path_mappings=parse_path_map("/data=/mnt/immich"), show_prefix="◈ ")
STYLES = builtin_styles()


def fake_look(asset: UUID, at: float, score: float = 0.8) -> FrameLook:
    rng = random.Random(f"{asset}/{at}")
    return FrameLook(
        asset_id=str(asset),
        at=at,
        quality=Quality(0.9, 0.9, 0.8, 0.5, 0.0, 1920, score),
        faces=(),
        point=(0.5, 0.5),
        region=None,
        signature=tuple(rng.randrange(256) for _ in range(12 * 12 * 3)),
    )


def family(immich: FakeImmich | None = None) -> tuple[FakeImmich, Show]:
    immich = immich or FakeImmich()
    album = immich.add_album(1, "Family")
    immich.add_video(album, 1, "2023-06-10T09:00:00")
    immich.add_video(album, 2, "2024-07-15T14:32:00")
    show = build_show(
        Album.model_validate(immich.albums[album]),
        [Asset.model_validate(v) for v in immich.videos[album]],
        OPTIONS,
    )
    return immich, show


def looks_of(show: Show) -> dict[UUID, list[FrameLook]]:
    return {e.asset_id: [fake_look(e.asset_id, t) for t in (1.0, 2.0, 3.0)] for e in show.episodes}


# --- the database -----------------------------------------------------------------------


async def test_models_match_the_migrations(engine: AsyncEngine) -> None:
    async with engine.connect() as connection:
        differences = await connection.run_sync(
            lambda sync: compare_metadata(MigrationContext.configure(sync), Base.metadata)
        )
    assert differences == []


async def test_frame_looks_are_kept_and_replaced(session: AsyncSession) -> None:
    registry = Registry(session)
    asset = asset_id(1)
    await registry.save_frame_looks(asset, "sum1", LOOK_VERSION, [fake_look(asset, 1).to_dict()])
    await registry.save_frame_looks(asset, "sum2", LOOK_VERSION, [], failed=True)
    await registry.commit()
    rows = await registry.frame_looks([asset, asset_id(2)])
    assert list(rows) == [asset]
    assert rows[asset].checksum == "sum2" and rows[asset].failed and rows[asset].looks == []


# --- the plan ---------------------------------------------------------------------------


def test_a_show_gets_every_picture() -> None:
    _, show = family()
    jobs = plan_show(show, looks_of(show), STYLES["mosaic"])
    assert set(jobs) == {
        (OutputKind.SERIES_POSTER, None),
        (OutputKind.LANDSCAPE, None),
        (OutputKind.FANART, None),
        (OutputKind.LOGO, None),
        (OutputKind.SEASON_POSTER, 2023),
        (OutputKind.SEASON_POSTER, 2024),
    }
    assert jobs[(OutputKind.LOGO, None)].frames == ()
    assert jobs[(OutputKind.FANART, None)].text == ""
    assert jobs[(OutputKind.SERIES_POSTER, None)].text == "Family", "without the prefix"
    season = jobs[(OutputKind.SEASON_POSTER, 2023)]
    assert season.text == "2023"
    assert {f.asset_id for f in season.frames} == {asset_id(1)}


def test_the_version_follows_what_the_picture_is_made_of() -> None:
    _, show = family()
    looks = looks_of(show)
    poster = (OutputKind.SERIES_POSTER, None)
    first = plan_show(show, looks, STYLES["mosaic"])[poster].version
    assert plan_show(show, looks, STYLES["mosaic"])[poster].version == first
    assert plan_show(show, looks, STYLES["film"])[poster].version != first
    assert plan_show(show, looks, STYLES["mosaic"], seed=5)[poster].version != first
    renamed = Show(**{**show.__dict__, "sort_title": "Holidays"})
    assert plan_show(renamed, looks, STYLES["mosaic"])[poster].version != first


def test_one_season_gets_no_season_posters() -> None:
    _, show = family()
    jobs = plan_show(show, looks_of(show), STYLES["mosaic"], season_posters=False)
    assert all(kind is not OutputKind.SEASON_POSTER for kind, _ in jobs)


def test_no_frames_no_pictures() -> None:
    _, show = family()
    assert plan_show(show, {}, STYLES["mosaic"]) == {}


def test_a_style_is_chosen_the_same_way_for_the_same_album() -> None:
    ids = sorted(STYLES)
    album = UUID(int=42)
    assert choose_style(album, ids) == choose_style(album, list(reversed(ids)))
    assert len({choose_style(UUID(int=n), ids) for n in range(60)}) > 3


def test_drawn_poster_takes_the_place_of_the_cover() -> None:
    _, show = family()
    show = Show(**{**show.__dict__, "cover_asset_id": asset_id(1)})
    root = PurePosixPath("Family")
    plain = picture_files(show, root, None, PICTURE_NAMES)
    assert [str(f.path) for f in plain] == ["Family/poster.jpg"]
    assert plain[0].image is not None and plain[0].image.artwork is None
    jobs = plan_show(show, looks_of(show), STYLES["mosaic"])
    drawn = {str(f.path): f for f in picture_files(show, root, jobs, PICTURE_NAMES)}
    assert set(drawn) == {
        "Family/folder.jpg",
        "Family/landscape.jpg",
        "Family/fanart.jpg",
        "Family/logo.png",
        "Family/Season 2023/poster.jpg",
        "Family/Season 2024/poster.jpg",
    }
    poster = drawn["Family/folder.jpg"]
    assert "Family/poster.jpg" not in drawn, "the cover gives way to the drawn poster"
    assert poster.kind is FileKind.IMAGE and poster.image is not None
    assert poster.image.artwork is not None
    assert poster.source_version == jobs[(OutputKind.SERIES_POSTER, None)].version


# --- a whole pass -----------------------------------------------------------------------


class FakeArtwork(ArtworkContext):
    """Draws a picture as a few bytes naming its job; counts what it draws."""

    def __init__(self, budget: float = 60.0) -> None:
        super().__init__(
            styles=STYLES,
            source=lambda a: (f"http://immich.test/api/assets/{a}/original", {}),
            budget_seconds=budget,
            detector=None,  # type: ignore[arg-type]
        )
        self.drawn: list[ArtworkJob] = []

    async def draw(self, job: ArtworkJob) -> bytes:
        self.drawn.append(job)
        return f"ART {job.kind.value} {job.season} {job.version}".encode()


@pytest.fixture
def looked_at(monkeypatch: pytest.MonkeyPatch) -> list[UUID]:
    """Looking at a video gives three made-up frames; the videos looked at are listed."""
    seen: list[UUID] = []

    def fake(video: Any, source: Any, detector: Any) -> list[FrameLook]:
        seen.append(video.asset_id)
        return [fake_look(video.asset_id, t) for t in (1.0, 2.0, 3.0)]

    monkeypatch.setattr(artwork_step, "look_at_video", fake)
    return seen


def files(root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in root.rglob("*")
        if p.is_file() and not p.is_symlink() and p.name != MARKER_NAME and p.suffix != ".nfo"
    }


async def one_pass(immich: FakeImmich, session: AsyncSession, out: Path, art: FakeArtwork) -> Any:
    async with immich.client() as client:
        (report,) = await sync_outputs(
            immich=client,
            registry=Registry(session),
            outputs=[Output(JellyfinLayout(), Executor(out, [PurePosixPath("/mnt/immich")]))],
            options=OPTIONS,
            full=False,
            artwork=art,
        )
    return report


@needs_links
async def test_a_pass_draws_the_pictures_once(
    session: AsyncSession, tmp_path: Path, looked_at: list[UUID]
) -> None:
    immich, _ = family()
    art = FakeArtwork()
    report = await one_pass(immich, session, tmp_path, art)
    assert report.ok
    written = files(tmp_path)
    folder = "Family [imm-00000001]"
    for name in ("folder.jpg", "landscape.jpg", "fanart.jpg", "logo.png"):
        assert written[f"{folder}/{name}"].startswith(b"ART "), name
    assert written[f"{folder}/Season 2023/poster.jpg"].startswith(b"ART season_poster 2023")
    assert sorted(looked_at) == [asset_id(1), asset_id(2)]
    assert len(art.drawn) == 6

    immich.touch(next(iter(immich.albums)), "2026-02-01T00:00:00.000Z")
    again = FakeArtwork()
    await one_pass(immich, session, tmp_path, again)
    assert again.drawn == [], "nothing changed: nothing is drawn again"
    assert sorted(looked_at) == [asset_id(1), asset_id(2)], "videos are looked at once"


@needs_links
async def test_a_show_waits_for_its_videos_and_keeps_the_cover(
    session: AsyncSession, tmp_path: Path, looked_at: list[UUID]
) -> None:
    immich, _ = family()
    album = next(iter(immich.albums))
    immich.albums[album]["albumThumbnailAssetId"] = str(asset_id(1))
    report = await one_pass(immich, session, tmp_path, FakeArtwork(budget=0))
    assert report.ok
    poster = files(tmp_path)["Family [imm-00000001]/poster.jpg"]
    assert poster.startswith(b"JPEG"), "no video looked at yet: the cover of the album"
    # The album was not stamped: the next quick pass reads it again and draws it.
    art = FakeArtwork()
    await one_pass(immich, session, tmp_path, art)
    written = files(tmp_path)
    assert written["Family [imm-00000001]/folder.jpg"].startswith(b"ART")
    assert "Family [imm-00000001]/poster.jpg" not in written, "the cover gave way"
    assert art.drawn


def test_kodi_gets_the_posters_of_seasons_in_the_nfo() -> None:
    from showrunner.targets.kodi.layout import KodiLayout

    _, show = family()
    jobs = plan_show(show, looks_of(show), STYLES["mosaic"])
    nfo = next(
        f
        for f in KodiLayout("smb://box/kodi").files(show, "Family", jobs)
        if f.path.name == "tvshow.nfo"
    )
    assert nfo.content is not None
    text = nfo.content.decode()
    assert (
        '<thumb aspect="poster" type="season" season="2023">'
        "smb://box/kodi/Family/Season 2023/poster.jpg</thumb>"
    ) in text
    plain = next(f for f in KodiLayout().files(show, "Family", jobs) if f.path.name == "tvshow.nfo")
    assert plain.content is not None and b"<thumb" not in plain.content
    names = {str(f.path) for f in KodiLayout().files(show, "Family", jobs)}
    assert "Family/clearlogo.png" in names and "Family/Season 2024/poster.jpg" in names


async def test_looks_read_again_after_they_were_replaced(session: AsyncSession) -> None:
    """The step reads the looks, writes new ones in the same session and reads them again: it
    must see the new ones (an upsert does not refresh what the session already holds)."""
    registry = Registry(session)
    asset = asset_id(1)
    await registry.save_frame_looks(asset, "sum", LOOK_VERSION - 1, [])
    await registry.commit()
    before = await registry.frame_looks([asset])  # held, as the step holds what it read
    assert before[asset].version == LOOK_VERSION - 1
    await registry.save_frame_looks(asset, "sum", LOOK_VERSION, [fake_look(asset, 1).to_dict()])
    await registry.commit()
    row = (await registry.frame_looks([asset]))[asset]
    assert row.version == LOOK_VERSION and len(row.looks) == 1
    assert before


# --- choices made on the page -----------------------------------------------------------


@needs_links
async def test_choices_from_the_page_reach_the_pictures(
    session: AsyncSession, tmp_path: Path, looked_at: list[UUID]
) -> None:
    immich, _ = family()
    album = next(iter(immich.albums))
    immich.albums[album]["albumThumbnailAssetId"] = str(asset_id(1))
    registry = Registry(session)
    folder = "Family [imm-00000001]"
    stamp = iter(f"2026-02-{day:02d}T00:00:00.000Z" for day in range(1, 28))

    async def again(art: FakeArtwork | None = None) -> FakeArtwork:
        immich.touch(album, next(stamp))
        art = art or FakeArtwork()
        await one_pass(immich, session, tmp_path, art)
        return art

    await again()
    style = (await registry.artworks())[album].style_id

    # The cover of the album as the poster: the drawn poster gives way.
    await registry.save_artwork(album, style, use_cover=True)
    await registry.commit()
    await again()
    written = files(tmp_path)
    assert written[f"{folder}/poster.jpg"].startswith(b"JPEG")
    assert f"{folder}/folder.jpg" not in written
    assert written[f"{folder}/landscape.jpg"].startswith(b"ART")

    # Frozen: the next pass keeps what is drawn; other frames then change nothing.
    await registry.save_artwork(album, style, use_cover=False, frozen="all", frozen_jobs=None)
    await registry.commit()
    await again()
    assert (await registry.artworks())[album].frozen_jobs
    await registry.save_artwork(album, style, seed=99)
    await registry.commit()
    assert (await again()).drawn == [], "frozen: nothing drawn again"

    # Not frozen any more, and its style switched off: another style is chosen.
    await registry.save_artwork(album, style, frozen="none", frozen_jobs=None)
    await registry.set_style_enabled(style, False)
    await registry.commit()
    drawn = (await again()).drawn
    assert drawn and all(job.style_id != style for job in drawn)
    assert (await registry.artworks())[album].style_id != style
