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
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from uuid import UUID

import anyio.to_thread

from showrunner.artwork.faces import FaceDetector
from showrunner.artwork.frames import FrameError, seconds
from showrunner.artwork.jobs import ArtworkJob, ShowArtwork, choose_style, plan_show
from showrunner.artwork.make import ArtworkError, Video, VideoSource, draw, look_at_video
from showrunner.artwork.select import LOOK_VERSION, FrameLook
from showrunner.artwork.style import Style
from showrunner.model.show import SINGLE_SEASON, Show
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

    styles = sorted(context.styles)
    chosen = await registry.artworks()
    for show, _ in shows:
        looks: dict[UUID, list[FrameLook]] = {}
        for episode in show.episodes:
            row = rows.get(episode.asset_id)
            if row is None or row.checksum != episode.checksum or row.version != LOOK_VERSION:
                # Not looked at yet: drawn from the other videos for now, and again later.
                result.incomplete.add(show.album_id)
                continue
            looks[episode.asset_id] = [
                look for look in map(FrameLook.from_dict, row.looks) if look is not None
            ]
        if not any(looks.values()):
            continue  # nothing to draw from yet: the cover of the album stays
        art = chosen.get(show.album_id)
        style_id = art.style_id if art is not None and art.style_id in context.styles else None
        if style_id is None:
            style_id = choose_style(show.album_id, styles)
            await registry.set_artwork_style(show.album_id, style_id)
        seed = art.seed if art is not None else 0
        jobs = plan_show(
            show,
            looks,
            context.styles[style_id],
            seed,
            season_posters=show.seasons != (SINGLE_SEASON,),
        )
        if jobs:
            result.shows[show.album_id] = jobs
    return result


__all__ = ["ArtworkContext", "ArtworkError", "ArtworkPlan", "plan_artwork"]
