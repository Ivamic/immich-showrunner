# SPDX-License-Identifier: AGPL-3.0-or-later
"""Which pictures a show gets and what goes into each: the plan, before anything is drawn.

A job holds everything a picture is made of — the style and its version, the frames chosen
(by video and time), the text and the seed. Its version is a hash of that: the picture is drawn
again only when the hash changes, as a preview from Immich is downloaded again only when it
changes there."""

from __future__ import annotations

import hashlib
import json
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from uuid import UUID

from showrunner.artwork.select import FrameLook, choose
from showrunner.artwork.style import OutputKind, Style
from showrunner.model.show import Show

RENDER_VERSION = 1
"""Raised when the renderer draws differently, so that every picture is made again."""
SHOW_OUTPUTS = (
    OutputKind.SERIES_POSTER,
    OutputKind.LANDSCAPE,
    OutputKind.FANART,
    OutputKind.LOGO,
)
FANART_SEED = 7919
"""The backdrop takes another choice of frames than the poster, so the two differ."""


@dataclass(frozen=True)
class ChosenFrame:
    asset_id: UUID
    at: float
    point: tuple[float, float]
    region: tuple[float, float, float, float] | None

    @classmethod
    def of(cls, look: FrameLook) -> ChosenFrame:
        return cls(UUID(look.asset_id), look.at, look.point, look.region)


@dataclass(frozen=True)
class ArtworkJob:
    album_id: UUID
    kind: OutputKind
    season: int | None
    style_id: str
    style_version: int
    text: str
    seed: int
    frames: tuple[ChosenFrame, ...]

    @property
    def version(self) -> str:
        data = [
            RENDER_VERSION,
            self.kind.value,
            self.season,
            self.style_id,
            self.style_version,
            self.text,
            self.seed,
            [
                [str(f.asset_id), round(f.at, 3), [round(v, 4) for v in f.point]]
                + ([[round(v, 4) for v in f.region]] if f.region else [])
                for f in self.frames
            ],
        ]
        digest = hashlib.sha256(json.dumps(data, ensure_ascii=False).encode()).hexdigest()
        return f"art-{digest[:32]}"


ArtworkKey = tuple[OutputKind, int | None]
ShowArtwork = Mapping[ArtworkKey, ArtworkJob]


def choose_style(album_id: UUID, style_ids: Sequence[str]) -> str:
    """A style for a new show: at random, but the same for the same album."""
    return random.Random(album_id.int).choice(sorted(style_ids))


def plan_show(
    show: Show,
    looks: Mapping[UUID, Sequence[FrameLook]],
    style: Style,
    seed: int = 0,
    *,
    season_posters: bool = True,
) -> dict[ArtworkKey, ArtworkJob]:
    """The pictures of a show. `looks` must cover its videos; a video without frames (one that
    could not be read) is left out. A show without any frame gets no pictures."""
    every = [look for episode in show.episodes for look in looks.get(episode.asset_id, ())]
    if not every:
        return {}
    limit = style.spec.max_frames
    title = show.sort_title
    jobs: dict[ArtworkKey, ArtworkJob] = {}

    def job(kind: OutputKind, season: int | None, text: str, chosen: list[FrameLook]) -> None:
        jobs[(kind, season)] = ArtworkJob(
            album_id=show.album_id,
            kind=kind,
            season=season,
            style_id=style.id,
            style_version=style.spec.version,
            text=text,
            seed=seed,
            frames=tuple(ChosenFrame.of(look) for look in chosen),
        )

    best = choose(every, limit, seed)
    job(OutputKind.SERIES_POSTER, None, title, best)
    job(OutputKind.LANDSCAPE, None, title, best)
    job(OutputKind.FANART, None, "", choose(every, limit, seed + FANART_SEED))
    job(OutputKind.LOGO, None, title, [])  # only the title
    if season_posters:
        for season in show.seasons:
            own = [
                look
                for episode in show.episodes
                if episode.season == season
                for look in looks.get(episode.asset_id, ())
            ]
            if own:
                job(OutputKind.SEASON_POSTER, season, str(season), choose(own, limit, seed))
    return jobs
