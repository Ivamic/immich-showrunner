# SPDX-License-Identifier: AGPL-3.0-or-later
"""The titles of the slideshows alone, as pictures: to look over the text of every album (its
name, the date, the places) in the style it gets, in minutes instead of the hours of drawing.

Writes nothing but the pictures, into the folder given; reads Immich and the database only.
An album whose slideshows were planned by a pass gets the titles of that plan, exactly (its
years and parts, the photos shown); any other gets one title a year from all its photos, as
near as can be told without looking at them."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from uuid import UUID

from showrunner.artwork.jobs import choose_style
from showrunner.artwork.paint import Frame
from showrunner.artwork.render import render
from showrunner.artwork.style import OutputKind, Style
from showrunner.immich.client import ImmichClient, ImmichError
from showrunner.immich.models import Album, Asset
from showrunner.model.naming import WHOLE_ALBUM, safe_name
from showrunner.model.show import SeasonMode
from showrunner.slideshow.photos import PhotoError, open_photo
from showrunner.slideshow.plan import Clip, places_of
from showrunner.slideshow.words import language_of
from showrunner.store.registry import Registry
from showrunner.sync.specials import plan_file

log = logging.getLogger(__name__)

UNTITLED = "Untitled album"
"""As the show of an album without a name is called (`build_show`)."""


@dataclass(frozen=True)
class Place:
    city: str
    country: str


@dataclass(frozen=True)
class Title:
    """A title to draw: the clip it heads (its text) and the photos its picture is made of."""

    clip: Clip
    photos: tuple[UUID, ...]
    planned: bool


async def preview_titles(
    immich: ImmichClient,
    registry: Registry,
    styles: Mapping[str, Style],
    out: Path,
    *,
    data_dir: Path | None = None,
    only: str | None = None,
    say: Callable[[str], None] = print,
) -> list[Path]:
    """Draw the title of every slideshow of every album (whose name has `only` in it) into
    `out` (a folder that is there), a picture each; the files written."""
    setting = await registry.slideshow_setting()
    language = language_of(setting.language if setting is not None else None)
    places = setting.places if setting is not None else True
    shows = await registry.shows()
    choices = await registry.album_slideshows()
    arts = await registry.artworks()
    written: list[Path] = []
    for album in await immich.albums():
        row = shows.get(album.id)
        if row is not None and row.hidden:
            continue
        name = (row.title if row is not None and row.title else None) or (
            album.album_name.strip() or UNTITLED
        )
        if only and only.casefold() not in name.casefold():
            continue
        choice = choices.get(album.id)
        if choice is not None and choice.enabled is False:
            say(f"{name}: slideshows are off for this album")
            continue
        photos = {p.id: p async for p in immich.album_photos(album.id)}
        if not photos:
            continue
        named = choice.places if choice is not None and choice.places is not None else places
        whole = row is not None and SeasonMode(row.season_mode) is SeasonMode.SINGLE
        titles = _planned(album, name, photos, data_dir, language, named)
        if titles is None:
            titles = _by_year(album, name, photos, language, named, whole=whole)
        art = arts.get(album.id)
        style_id = art.style_id if art is not None and art.style_id in styles else None
        style = styles[style_id or choose_style(album.id, sorted(styles))]
        for title in titles:
            path = out / _file_name(name, title.clip)
            frames = await _frames(immich, photos, title.photos[: style.spec.max_frames])
            await asyncio.to_thread(_draw, style, frames, name, title.clip, path)
            written.append(path)
            how = "as planned" if title.planned else "not planned yet: one a year"
            say(f"{path.name}  [{style.id}; {how}]")
    return written


def _planned(
    album: Album,
    name: str,
    photos: Mapping[UUID, Asset],
    data_dir: Path | None,
    language: str,
    places: bool,
) -> list[Title] | None:
    """The titles of the slideshows a pass planned for the album, or None without a plan."""
    if data_dir is None:
        return None
    try:
        data = json.loads(plan_file(data_dir, album.id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    titles = []
    for item in data.get("slideshows", []):
        shown = [
            UUID(p["id"])
            for p in sorted(item.get("photos", []), key=lambda p: p["taken"])
            if p.get("fate") == "shown"
        ]
        if not shown:
            continue
        taken = [datetime.fromisoformat(p["taken"]) for p in item["photos"] if p["fate"] == "shown"]
        clip = _clip(album, name, int(item["year"]), int(item["part"]), taken, language)
        if places:
            clip = _with_places(clip, [photos[i] for i in shown if i in photos])
        titles.append(Title(clip, tuple(shown), planned=True))
    return titles or None


def _by_year(
    album: Album,
    name: str,
    photos: Mapping[UUID, Asset],
    language: str,
    places: bool,
    *,
    whole: bool,
) -> list[Title]:
    """One title a year (the whole album for one season) from all its photos, its picture from
    photos spread over the year."""
    years: dict[int, list[Asset]] = {}
    for photo in sorted(photos.values(), key=lambda p: p.local_date_time):
        years.setdefault(WHOLE_ALBUM if whole else photo.local_date_time.year, []).append(photo)
    titles = []
    for year, every in sorted(years.items()):
        taken = [p.local_date_time.replace(tzinfo=None) for p in every]
        clip = _clip(album, name, year, 0, taken, language)
        if places:
            clip = _with_places(clip, every)
        step = max(1, len(every) // 8)
        titles.append(Title(clip, tuple(p.id for p in every[::step]), planned=False))
    return titles


def _clip(
    album: Album, name: str, year: int, part: int, taken: Sequence[datetime], language: str
) -> Clip:
    return Clip(
        album_id=album.id,
        year=year,
        part=part,
        first=min(taken),
        last=max(taken),
        shots=(),
        left_out=0,
        title=name,
        credits=False,
        language=language,
    )


def _draw(style: Style, frames: list[Frame], name: str, clip: Clip, path: Path) -> None:
    picture = render(style, OutputKind.LANDSCAPE, frames, name, 0, clip.under_title)
    picture.image.convert("RGB").save(path, quality=90)


def _with_places(clip: Clip, photos: Sequence[Asset]) -> Clip:
    placed = [_place(p) for p in photos]
    return replace(clip, places=places_of(placed))


def _place(photo: Asset) -> Place:
    exif = photo.exif_info
    return Place((exif.city or "") if exif else "", (exif.country or "") if exif else "")


async def _frames(
    immich: ImmichClient, photos: Mapping[UUID, Asset], ids: Sequence[UUID]
) -> list[Frame]:
    """The previews of the photos (enough for a title), those that can be read."""
    frames = []
    for asset_id in ids:
        photo = photos.get(asset_id)
        try:
            edited = photo is not None and photo.is_edited
            content, _ = await immich.photo(asset_id, full=False, edited=edited)
            image, _ = open_photo(content)
        except (ImmichError, PhotoError) as exc:
            log.warning("titles: the photo %s could not be read: %s", asset_id, exc)
            continue
        frames.append(Frame(image=image))
    return frames


def _file_name(name: str, clip: Clip) -> str:
    when = "all" if clip.year == WHOLE_ALBUM else str(clip.year)
    part = f" part {clip.part}" if clip.part else ""
    return safe_name(f"{name} - {when}{part}") + ".jpg"


__all__ = ["preview_titles"]
