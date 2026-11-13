# SPDX-License-Identifier: AGPL-3.0-or-later
"""An album as a show: which videos are episodes, in which season, under which number and title."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import PurePosixPath
from uuid import UUID

from showrunner.config import PathMapping
from showrunner.immich.models import Album, Asset
from showrunner.model.naming import episode_file_stem, file_extension
from showrunner.model.paths import map_path

VISIBLE = frozenset({"timeline", "archive"})
SINGLE_SEASON = 1


class SeasonMode(StrEnum):
    YEAR = "year"  # a season per year of filming
    SINGLE = "single"  # the whole album is season 1


class SkipReason(StrEnum):
    NOT_A_VIDEO = "not_a_video"
    TRASHED = "trashed"
    OFFLINE = "offline"
    HIDDEN = "hidden"
    NO_PATH_MAPPING = "no_path_mapping"
    NO_EXTENSION = "no_extension"


@dataclass(frozen=True)
class Options:
    path_mappings: Sequence[PathMapping]
    show_prefix: str = ""
    person_prefix: str = ""
    title_max_length: int = 80
    # strftime format of the title of a video without a usable description.
    date_title_format: str = "%Y-%m-%d %H:%M"
    season_mode: SeasonMode = SeasonMode.YEAR


@dataclass(frozen=True)
class EpisodePerson:
    id: UUID
    name: str  # with the prefix


@dataclass(frozen=True)
class Episode:
    asset_id: UUID
    title: str
    plot: str
    filmed_at: datetime
    season: int
    number: int
    file_stem: str
    extension: str
    link_target: PurePosixPath
    people: tuple[EpisodePerson, ...] = ()
    # Changes when the preview of the video changes in Immich.
    picture_version: str = ""


@dataclass(frozen=True)
class Skipped:
    asset_id: UUID
    file_name: str
    reason: SkipReason


@dataclass(frozen=True)
class Show:
    album_id: UUID
    title: str  # with the prefix
    sort_title: str
    plot: str
    episodes: tuple[Episode, ...]
    skipped: tuple[Skipped, ...] = field(default=())
    # The asset whose picture is the cover of the album, if it has one.
    cover_asset_id: UUID | None = None

    @property
    def seasons(self) -> tuple[int, ...]:
        return tuple(sorted({e.season for e in self.episodes}))


def split_description(description: str, max_length: int) -> tuple[str | None, str]:
    """The title and the plot of a video from its description in Immich.

    The first line is the title when it is not longer than `max_length`; the rest is the plot.
    Otherwise there is no title and the whole description is the plot."""
    text = description.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return None, ""
    first, _, rest = text.partition("\n")
    first = first.strip()
    if first and len(first) <= max_length:
        return first, rest.strip()
    return None, text


def skip_reason(asset: Asset) -> SkipReason | None:
    if asset.type != "VIDEO":
        return SkipReason.NOT_A_VIDEO
    if asset.is_trashed:
        return SkipReason.TRASHED
    if asset.is_offline:
        return SkipReason.OFFLINE
    if asset.visibility not in VISIBLE:
        return SkipReason.HIDDEN
    return None


def build_show(album: Album, assets: Iterable[Asset], options: Options) -> Show:
    """Turn the videos of an album into the episodes of a show, in the order of filming."""
    skipped: list[Skipped] = []
    drafts: list[tuple[Asset, PurePosixPath, str]] = []
    seen: set[UUID] = set()
    for asset in assets:
        if asset.id in seen:
            continue
        seen.add(asset.id)
        reason = skip_reason(asset)
        target = None if reason else map_path(asset.original_path, options.path_mappings)
        extension = file_extension(asset.original_path)
        if reason is None and target is None:
            reason = SkipReason.NO_PATH_MAPPING
        if reason is None and not extension:
            reason = SkipReason.NO_EXTENSION
        if reason is not None or target is None:
            skipped.append(
                Skipped(asset.id, asset.original_file_name, reason or SkipReason.NO_PATH_MAPPING)
            )
            continue
        drafts.append((asset, target, extension))

    # The id breaks ties, so that the order is the same on every run.
    drafts.sort(key=lambda d: (d[0].local_date_time, d[0].id.hex))

    episodes: list[Episode] = []
    counters: dict[int, int] = {}
    for asset, target, extension in drafts:
        season = (
            asset.local_date_time.year if options.season_mode is SeasonMode.YEAR else SINGLE_SEASON
        )
        counters[season] = counters.get(season, 0) + 1
        title, plot = split_description(asset.description, options.title_max_length)
        episodes.append(
            Episode(
                asset_id=asset.id,
                title=title or asset.local_date_time.strftime(options.date_title_format),
                plot=plot,
                filmed_at=asset.local_date_time,
                season=season,
                number=counters[season],
                file_stem=episode_file_stem(
                    asset.local_date_time, asset.original_file_name, asset.id
                ),
                extension=extension,
                link_target=target,
                people=_people(asset, options.person_prefix),
                picture_version=asset.thumbhash or asset.updated_at.isoformat(),
            )
        )

    name = album.album_name.strip() or "Untitled album"
    return Show(
        album_id=album.id,
        title=f"{options.show_prefix}{name}",
        sort_title=name,
        plot=album.description.strip(),
        episodes=tuple(episodes),
        skipped=tuple(skipped),
        cover_asset_id=album.album_thumbnail_asset_id,
    )


def _people(asset: Asset, prefix: str) -> tuple[EpisodePerson, ...]:
    """People with a name, each once, in the order of Immich. A person without a name is someone
    the user of the key has not named, and does not go to the media server."""
    result: list[EpisodePerson] = []
    seen: set[UUID] = set()
    for person in asset.people:
        name = person.name.strip()
        if name and person.id not in seen:
            seen.add(person.id)
            result.append(EpisodePerson(person.id, f"{prefix}{name}"))
    return tuple(result)
