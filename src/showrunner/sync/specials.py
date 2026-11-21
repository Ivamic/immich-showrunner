# SPDX-License-Identifier: AGPL-3.0-or-later
"""Slideshows in the sync: which ones an album has (the cut list of each year, put to music),
and drawing those whose cut list changed before the files are written.

A slideshow is an episode of Season 0, "Photos 2024", placed after its year. Its file keeps its
name while what it holds changes: a new photo in the year gives a new cut list, a new version,
and the slideshow is drawn again; until it is, the one drawn before stays in the library (D-101).

Drawing takes minutes: a pass draws what fits in its time budget, the newest years first, and
leaves the rest (and the albums they belong to unstamped) to the next pass. A slideshow is
drawn into the data folder, copied into every output folder that wants it, and the drawn file
removed at the end of the pass: no copy is kept (D-101)."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID

from showrunner.artwork.jobs import choose_style
from showrunner.artwork.worker import ArtworkWorker, music_task, render_task, render_worker
from showrunner.immich.client import ImmichClient, ImmichError
from showrunner.model.show import SINGLE_SEASON, Show, Special
from showrunner.slideshow.content import album_mood
from showrunner.slideshow.library import (
    Piece,
    ensure_set,
    own_pieces,
    pending,
    remember,
    set_pieces,
    tracks,
)
from showrunner.slideshow.music import MusicAnalysis, MusicError
from showrunner.slideshow.plan import Clip, plan_album
from showrunner.slideshow.render import RenderError, RenderOptions
from showrunner.slideshow.score import Track, choose_tracks, fit_to_music
from showrunner.store.registry import Registry
from showrunner.sync.slideshow import PhotoReport, plan_inputs

log = logging.getLogger(__name__)

TITLE = "Photos {year}"
PART_TITLE = "Photos {year} ({part}/{parts})"


@dataclass
class SpecialsContext:
    """What the slideshows need in a pass. Drawing runs in a worker process of its own."""

    data_dir: Path
    full: bool
    """The key may download: photos are drawn from their full size."""
    styles: Sequence[str]
    credits: bool = True
    threads: int = 2
    budget_seconds: float = 600.0
    worker: ArtworkWorker = field(default_factory=render_worker)
    clock: Callable[[], float] = time.monotonic
    _pieces: dict[str, Piece] = field(default_factory=dict)
    _drawn: dict[str, tuple[Path, str]] = field(default_factory=dict)
    _started: float | None = None

    @property
    def work(self) -> Path:
        return self.data_dir / "slideshows"

    async def music(self) -> list[Track]:
        """The music slideshows may use: the set (downloaded when missing) and the user's own,
        each looked at once."""
        await ensure_set(self.data_dir)
        pieces = set_pieces(self.data_dir) + own_pieces(self.data_dir)
        cache = self.data_dir / "music" / ".analysis"
        for piece in pending(pieces, cache):
            try:
                data = await self.worker.run(music_task, str(piece.path))
                found = MusicAnalysis.from_dict(data)
                if found is None:  # pragma: no cover - the worker runs the same code
                    continue
                remember(piece, cache, found)
            except MusicError as exc:
                remember(piece, cache, exc)
        self._pieces = {p.id: p for p in pieces}
        return tracks(pieces, cache)

    def drawn(self, version: str) -> bool:
        return version in self._drawn

    def budget_left(self) -> bool:
        if self._started is None:
            self._started = self.clock()
        return self.clock() - self._started < self.budget_seconds

    @property
    def progress_file(self) -> Path:
        """What is being drawn now and how many wait (for the page)."""
        return self.work / "progress.json"

    @property
    def frames_file(self) -> Path:
        """How far the drawing is, written by the worker."""
        return self.work / "frames.json"

    def note(self, **values: object) -> None:
        """Note what the drawing does now, for the page (written whole, never half)."""
        self.work.mkdir(parents=True, exist_ok=True)
        partial = self.progress_file.with_name(".progress.json.part")
        try:
            partial.write_text(json.dumps(values, default=str), encoding="utf-8")
            os.replace(partial, self.progress_file)
        except OSError:
            pass

    async def draw(
        self, immich: ImmichClient, special: Special, album_id: UUID | None = None, queue: int = 0
    ) -> tuple[Path, str]:
        """The slideshow drawn (once a pass for all outputs) and the SHA-256 of its file.
        Raises RenderError, or ImmichError when a photo can not be had."""
        kept = self._drawn.get(special.version)
        if kept is not None:
            return kept
        clip: Clip = special.clip
        self.frames_file.unlink(missing_ok=True)
        self.note(
            album_id=album_id,
            show=clip.title,
            title=special.title,
            started=datetime.now(UTC).isoformat(),
            queue=queue,
        )
        folder = self.work / "work" / special.version
        folder.mkdir(parents=True, exist_ok=True)
        try:
            photos = {}
            for asset_id in clip.photos:
                content, _ = await immich.photo(asset_id, full=self.full)
                path = folder / f"{asset_id}.photo"
                path.write_bytes(content)
                photos[str(asset_id)] = str(path)
            music = {
                part.track: str(self._pieces[part.track].path)
                for part in clip.music
                if part.track in self._pieces
            }
            out = self.work / f"{special.version}.mp4"
            await self.worker.run(
                render_task,
                clip.to_dict(),
                photos,
                special.style_id,
                str(out),
                {"threads": self.threads},
                music,
                str(self.frames_file),
            )
        finally:
            shutil.rmtree(folder, ignore_errors=True)
        digest = _sha256(out)
        self._drawn[special.version] = (out, digest)
        return out, digest

    def clean(self) -> None:
        """Remove what was drawn in this pass: it is in the output folders now (D-101)."""
        for path, _ in self._drawn.values():
            path.unlink(missing_ok=True)
        self._drawn.clear()
        self._started = None
        self.progress_file.unlink(missing_ok=True)
        self.frames_file.unlink(missing_ok=True)


async def plan_specials(
    shows: Sequence[tuple[Show, str]],
    photos: PhotoReport,
    registry: Registry,
    context: SpecialsContext,
) -> list[tuple[Show, str]]:
    """The shows with their slideshows: for each album read in this pass, the cut list of each
    year with enough photos, put to music of the album's mood."""
    album_ids = [show.album_id for show, _ in shows if show.album_id in photos.photos]
    if not album_ids:
        return list(shows)
    rows = await registry.photo_looks(
        [asset.id for album in album_ids for asset in photos.photos[album]]
    )
    off = await registry.disabled_music()
    music = [t for t in await context.music() if t.id not in off]
    chosen = await registry.artworks()
    choices = await registry.album_slideshows()
    result = []
    for show, folder in shows:
        assets = photos.photos.get(show.album_id)
        if assets is None:
            result.append((show, folder))
            continue
        choice = choices.get(show.album_id)
        if choice is not None and choice.enabled is False:
            # Switched off for this album on the page: its slideshows go.
            await registry.save_album_slideshow(show.album_id, planned=[])
            result.append((show, folder))
            continue
        inputs = plan_inputs(assets, rows)
        art = chosen.get(show.album_id)
        seed = art.seed if art is not None else 0
        style = art.style_id if art is not None and art.style_id in context.styles else None
        style = style or choose_style(show.album_id, list(context.styles))
        auto = album_mood([p.embedding for p in inputs if p.embedding is not None])
        mood = choice.mood if choice is not None and choice.mood else auto
        music_seed = choice.music_seed if choice is not None else 0
        key = f"{show.album_id}/{seed}" + (f"/{music_seed}" if music_seed else "")
        pieces = choose_tracks(music, mood, key) if music else []
        clips = plan_album(
            show.album_id, show.sort_title, inputs, seed=seed, credits=context.credits
        )
        clips = [fit_to_music(clip, pieces) for clip in clips]
        specials = specials_of(show, clips, style)
        looked = {p.asset_id for p in inputs}
        waiting: dict[int, int] = {}
        for asset in assets:
            if asset.id not in looked:
                year = asset.local_date_time.year
                waiting[year] = waiting.get(year, 0) + 1
        await registry.save_album_slideshow(
            show.album_id,
            auto_mood=auto,
            planned=[summary(s, waiting.get(s.year, 0)) for s in specials],
        )
        result.append((replace(show, specials=specials), folder))
    return result


def summary(special: Special, not_looked: int = 0) -> dict[str, object]:
    """What the page shows of a slideshow planned in this pass, with why photos were left out;
    `not_looked`: photos of its year not looked at yet (they wait for later passes)."""
    clip: Clip = special.clip
    return {
        "report": {**clip.report, "not_looked": not_looked},
        "year": special.year,
        "part": special.part,
        "title": special.title,
        "seconds": round(clip.seconds, 1),
        "photos": len(clip.photos),
        "left_out": clip.left_out,
        "music": list(clip.music_credits),
        "version": special.version,
    }


def specials_of(show: Show, clips: Sequence[Clip], style_id: str) -> tuple[Special, ...]:
    parts: dict[int, int] = {}
    for clip in clips:
        parts[clip.year] = parts.get(clip.year, 0) + 1
    specials = []
    for number, clip in enumerate(sorted(clips, key=lambda c: (c.year, c.part)), start=1):
        count = parts[clip.year]
        title = (
            PART_TITLE.format(year=clip.year, part=clip.part, parts=count)
            if clip.part
            else TITLE.format(year=clip.year)
        )
        specials.append(
            Special(
                year=clip.year,
                part=clip.part,
                parts=count,
                number=number,
                title=title,
                plot="\n".join(f"Music: {line}" for line in clip.music_credits),
                aired=date(clip.year, 12, 31),
                after_season=_season_before(show, clip.year),
                version=f"{clip.version}-{style_id}",
                clip=clip,
                style_id=style_id,
            )
        )
    return tuple(specials)


def _season_before(show: Show, year: int) -> int | None:
    """The season a slideshow of `year` comes after: its year, or the last season before it;
    with one season for all years, that season. None when the show has no season before it."""
    seasons = show.seasons
    if seasons == (SINGLE_SEASON,):
        return SINGLE_SEASON
    earlier = [s for s in seasons if s <= year]
    return earlier[-1] if earlier else None


def newest_first(specials: Mapping[str, Special]) -> list[str]:
    return sorted(specials, key=lambda key: (-specials[key].year, specials[key].part))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "ImmichError",
    "RenderError",
    "RenderOptions",
    "SpecialsContext",
    "newest_first",
    "plan_specials",
    "specials_of",
]
