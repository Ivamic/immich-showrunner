# SPDX-License-Identifier: AGPL-3.0-or-later
"""The artwork step of a pass: look at the videos not looked at yet, then plan the pictures of
every show.

Looking at a video takes about a second, so a large library is looked at over several passes:
each pass stops after its time budget. A show with videos still to look at is drawn from the
videos looked at so far (or keeps the cover of its album while there are none) and is not
stamped, so that the next quick pass comes back to it."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import anyio.to_thread

from showrunner.artwork.faces import FaceDetector
from showrunner.artwork.frames import FrameError, seconds
from showrunner.artwork.jobs import (
    ArtworkJob,
    ArtworkKey,
    ShowArtwork,
    choose_style,
    plan_show,
)
from showrunner.artwork.make import ArtworkError, Video, VideoSource, draw, look_at_video
from showrunner.artwork.select import LOOK_VERSION, FrameLook
from showrunner.artwork.style import OutputKind, Style
from showrunner.model.show import SINGLE_SEASON, Show
from showrunner.store.models import FrameLookRow
from showrunner.store.registry import Registry

log = logging.getLogger(__name__)


@dataclass
class ArtworkContext:
    """What the artwork step needs; built once for the app."""

    styles: Mapping[str, Style]
    source: VideoSource
    budget_seconds: float = 240.0
    detector: FaceDetector = field(default_factory=FaceDetector)
    clock: Callable[[], float] = time.monotonic

    async def draw(self, job: ArtworkJob) -> bytes:
        return await anyio.to_thread.run_sync(draw, job, self.styles, self.source)


@dataclass
class ArtworkPlan:
    shows: dict[UUID, ShowArtwork] = field(default_factory=dict)
    # Shows with videos still to look at: they keep the cover and are looked at again.
    incomplete: set[UUID] = field(default_factory=set)
    looked: int = 0
    unreadable: int = 0


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
            found = await anyio.to_thread.run_sync(
                look_at_video, video, context.source, context.detector
            )
            failed = False
            result.looked += 1
        except FrameError as exc:
            log.warning("video %s could not be read for artwork: %s", video.asset_id, exc)
            found, failed = [], True
            result.unreadable += 1
        data = [item.to_dict() for item in found]
        await registry.save_frame_looks(video.asset_id, video.checksum, LOOK_VERSION, data, failed)
    if result.looked or result.unreadable:
        await registry.commit()
        rows = await registry.frame_looks(videos.keys())

    disabled = await registry.disabled_styles()
    usable = sorted(s for s in context.styles if s not in disabled) or sorted(context.styles)
    chosen = await registry.artworks()
    for show, _ in shows:
        looks, waiting = looks_of(show, rows)
        if waiting:
            # Not looked at yet: drawn from the other videos for now, and again later.
            result.incomplete.add(show.album_id)
        art = chosen.get(show.album_id)
        frozen = art.frozen if art is not None else NOT_FROZEN
        style_id = art.style_id if art is not None and art.style_id in context.styles else None
        if style_id is None or (style_id in disabled and frozen == NOT_FROZEN):
            style_id = choose_style(show.album_id, usable)
            await registry.save_artwork(show.album_id, style_id)
        jobs = (
            plan_show(
                show,
                looks,
                context.styles[style_id],
                art.seed if art is not None else 0,
                season_posters=show.seasons != (SINGLE_SEASON,),
            )
            if any(looks.values())
            else {}
        )
        if art is not None and frozen != NOT_FROZEN:
            if art.frozen_jobs is None:
                # Frozen on the page: what is drawn now is kept from now on.
                await registry.save_artwork(
                    show.album_id, style_id, frozen_jobs=[j.to_dict() for j in jobs.values()]
                )
            else:
                jobs = with_frozen(jobs, art.frozen_jobs, frozen, show.seasons)
        if art is not None and art.use_cover:
            jobs.pop((OutputKind.SERIES_POSTER, None), None)
        if jobs:
            result.shows[show.album_id] = jobs
    return result


NOT_FROZEN = "none"
FROZEN_SHOW = "show"
FROZEN_ALL = "all"


def looks_of(
    show: Show, rows: Mapping[UUID, FrameLookRow]
) -> tuple[dict[UUID, list[FrameLook]], bool]:
    """The looks of the videos of a show, and whether some videos are still to look at."""
    looks: dict[UUID, list[FrameLook]] = {}
    waiting = False
    for episode in show.episodes:
        row = rows.get(episode.asset_id)
        if row is None or row.checksum != episode.checksum or row.version != LOOK_VERSION:
            waiting = True
            continue
        looks[episode.asset_id] = [
            look for look in map(FrameLook.from_dict, row.looks) if look is not None
        ]
    return looks, waiting


def with_frozen(
    jobs: Mapping[ArtworkKey, ArtworkJob],
    frozen_jobs: list[dict[str, Any]],
    frozen: str,
    seasons: Sequence[int],
) -> dict[ArtworkKey, ArtworkJob]:
    """The pictures as frozen take the place of the ones planned now. Frozen as `show`, only
    the pictures of the show are kept; frozen as `all`, the posters of the seasons too, while a
    new season gets its poster as usual and a season that is gone loses it."""
    result = dict(jobs)
    for job in map(ArtworkJob.from_dict, frozen_jobs):
        if job.season is None or (frozen == FROZEN_ALL and job.season in seasons):
            result[(job.kind, job.season)] = job
    return result


__all__ = [
    "ArtworkContext",
    "ArtworkError",
    "ArtworkPlan",
    "looks_of",
    "plan_artwork",
    "with_frozen",
]
