# SPDX-License-Identifier: AGPL-3.0-or-later
"""The artwork step of a pass: look at the videos not looked at yet, then plan the pictures of
every show.

Looking at a video takes about a second, so a large library is looked at over several passes:
each pass stops after its time budget. A show with videos still to look at is drawn from the
videos looked at so far (or keeps the cover of its album while there are none) and is not
stamped, so that the next quick pass comes back to it.

What the user chose on the page counts here: the style of the album, the cover as its poster,
other frames for a single picture (a seed of its own), and pinned pictures, which are kept as
they were drawn whatever happens to the album."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from showrunner.artwork.frames import FrameError, seconds
from showrunner.artwork.jobs import (
    ArtworkJob,
    ArtworkKey,
    ShowArtwork,
    choose_style,
    plan_show,
    slot_key,
)
from showrunner.artwork.make import ArtworkError, Video
from showrunner.artwork.select import LOOK_VERSION, FrameLook
from showrunner.artwork.style import OutputKind, Style
from showrunner.artwork.worker import (
    ArtworkWorker,
    HttpSource,
    draw_task,
    look_task,
    shared_worker,
)
from showrunner.model.show import SINGLE_SEASON, Show
from showrunner.store.models import FrameLookRow
from showrunner.store.registry import Registry

log = logging.getLogger(__name__)


@dataclass
class ArtworkContext:
    """What the artwork step needs. The slow work runs in the worker process."""

    styles: Mapping[str, Style]
    source: HttpSource
    budget_seconds: float = 240.0
    worker: ArtworkWorker = field(default_factory=shared_worker)
    clock: Callable[[], float] = time.monotonic

    async def look(self, video: Video) -> list[FrameLook]:
        """The frames of a video, looked at. Raises FrameError."""
        data = await self.worker.run(
            look_task, str(video.asset_id), video.checksum, video.seconds, self.source
        )
        return [look for look in map(FrameLook.from_dict, data) if look is not None]

    async def draw(self, job: ArtworkJob) -> bytes:
        """A picture, encoded. Raises ArtworkError."""
        return await self.worker.run(draw_task, job.to_dict(), self.source)


@dataclass
class ArtworkPlan:
    shows: dict[UUID, ShowArtwork] = field(default_factory=dict)
    # Shows with videos still to look at, and how many: drawn from the others for now.
    waiting: dict[UUID, int] = field(default_factory=dict)
    looked: int = 0
    unreadable: int = 0

    @property
    def incomplete(self) -> set[UUID]:
        return set(self.waiting)


async def plan_artwork(
    shows: list[tuple[Show, str]], registry: Registry, context: ArtworkContext
) -> ArtworkPlan:
    result = ArtworkPlan()
    videos = {
        episode.asset_id: Video(episode.asset_id, episode.checksum, seconds(episode.duration_ms))
        for show, _ in shows
        for episode in show.episodes
    }
    rows = await registry.frame_looks(videos.keys())
    started = context.clock()
    for video in videos.values():
        row = rows.get(video.asset_id)
        if row is not None and row.checksum == video.checksum and row.version == LOOK_VERSION:
            continue
        if context.clock() - started >= context.budget_seconds:
            break
        try:
            found = await context.look(video)
            failed = False
            result.looked += 1
        except FrameError as exc:
            log.warning("video %s could not be read for artwork: %s", video.asset_id, exc)
            found, failed = [], True
            result.unreadable += 1
        data = [item.to_dict() for item in found]
        await registry.save_frame_looks(video.asset_id, video.checksum, LOOK_VERSION, data, failed)
        # Each look is kept at once: the work of a long pass is not lost if it stops.
        await registry.commit()
    if result.looked or result.unreadable:
        rows = await registry.frame_looks(videos.keys())

    disabled = await registry.disabled_styles()
    usable = sorted(s for s in context.styles if s not in disabled) or sorted(context.styles)
    chosen = await registry.artworks()
    for show, _ in shows:
        looks, waiting = looks_of(show, rows)
        if waiting:
            result.waiting[show.album_id] = waiting
        art = chosen.get(show.album_id)
        style_id = art.style_id if art is not None and art.style_id in context.styles else None
        if style_id is None or style_id in disabled:
            style_id = choose_style(show.album_id, usable)
            await registry.save_artwork(show.album_id, style_id)
        jobs = (
            plan_show(
                show,
                looks,
                context.styles[style_id],
                art.seed if art is not None else 0,
                seeds=art.slot_seeds if art is not None else None,
                season_posters=show.seasons != (SINGLE_SEASON,),
            )
            if any(looks.values())
            else {}
        )
        if art is not None and art.pinned_jobs:
            jobs = with_pinned(jobs, art.pinned_jobs, show.seasons)
        if art is not None and art.use_cover:
            jobs.pop((OutputKind.SERIES_POSTER, None), None)
        drawn = {slot_key(*key): job.to_dict() for key, job in jobs.items()}
        if art is None or (art.drawn_jobs or {}) != drawn:
            await registry.save_artwork(show.album_id, style_id, drawn_jobs=drawn)
        if jobs:
            result.shows[show.album_id] = jobs
    return result


def looks_of(
    show: Show, rows: Mapping[UUID, FrameLookRow]
) -> tuple[dict[UUID, list[FrameLook]], int]:
    """The looks of the videos of a show, and how many videos are still to look at."""
    looks: dict[UUID, list[FrameLook]] = {}
    waiting = 0
    for episode in show.episodes:
        row = rows.get(episode.asset_id)
        if row is None or row.checksum != episode.checksum or row.version != LOOK_VERSION:
            waiting += 1
            continue
        looks[episode.asset_id] = [
            look for look in map(FrameLook.from_dict, row.looks) if look is not None
        ]
    return looks, waiting


def with_pinned(
    jobs: Mapping[ArtworkKey, ArtworkJob],
    pinned: Mapping[str, dict[str, Any]],
    seasons: tuple[int, ...],
) -> dict[ArtworkKey, ArtworkJob]:
    """Pinned pictures take the place of the ones planned now; the poster of a season that is
    gone goes with it."""
    result = dict(jobs)
    for data in pinned.values():
        job = ArtworkJob.from_dict(data)
        if job.season is None or job.season in seasons:
            result[(job.kind, job.season)] = job
    return result


__all__ = [
    "ArtworkContext",
    "ArtworkError",
    "ArtworkPlan",
    "looks_of",
    "plan_artwork",
    "with_pinned",
]
