# SPDX-License-Identifier: AGPL-3.0-or-later
"""The cut list of a slideshow: which photos, in what order, for how long, how the camera moves
over each and how one gives way to the next. Pure logic and deterministic: the same photos give
the same list, and the version of a list (a hash of it) says when a slideshow is to be made again.

The rules (see D-091, D-097):

- one slideshow per year, of 3 to 5 minutes; a long year is cut into parts between scenes;
- the order is the time of taking; a scene ends after a pause of more than two hours or a move of
  more than about 20 km;
- screenshots, documents and receipts are left out; a series of near copies becomes its best
  photo; a scene gives at most a dozen photos;
- about four seconds a photo, longer for groups and panoramas, shorter in a busy scene;
- the camera moves slowly towards the faces (or what draws the eye), zooming in and out in turn;
  a standing photo is shown whole over a blurred copy of itself, a panorama is travelled along;
- a dissolve within a scene, longer between photos alike; a fade through black between scenes."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import UUID

import numpy as np

from showrunner.artwork.select import likeness
from showrunner.slideshow.content import is_junk
from showrunner.slideshow.embed import similarity
from showrunner.slideshow.photos import PhotoLook, distance

PLAN_VERSION = 1
"""Raised when the rules change, so that every slideshow is made again."""
ASPECT = 16 / 9

SCENE_GAP = timedelta(hours=2)
SCENE_DISTANCE_KM = 20.0
SERIES_WINDOW = timedelta(minutes=15)
SERIES_SIMILARITY = 0.92
"""Embeddings this alike, taken within SERIES_WINDOW, are one series: only the best stays."""
SERIES_HASH_BITS = 10
SERIES_LIKENESS = 0.9
"""Without embeddings: hashes this close and colours this alike make a series."""
MAX_PER_SCENE = 12
POOR = 0.2
MIN_PHOTOS = 6
"""A year with fewer photos gets no slideshow."""

PHOTO_SECONDS = 4.0
MIN_SECONDS, MAX_SECONDS = 3.0, 5.0
BUSY_SCENE = 8
TITLE_SECONDS = 3.5
CREDITS_SECONDS = 4.0
CLIP_MAX_SECONDS = 300.0
CLIP_TARGET_SECONDS = 240.0

ZOOM = 1.12
MIN_ZOOM = 1.04
"""Less than this does not look like a move: the camera glides instead."""
GLIDE = 0.12
"""How far a gliding camera travels, as a share of its frame."""
STANDING_ZOOM = 1.06
STANDING = 1.25
"""Photos narrower than this (width / height) are shown whole over a blurred copy."""
PANORAMA = 2.2

DISSOLVE_MIN, DISSOLVE_MAX = 0.6, 1.4
FADE_BLACK_SECONDS = 1.0


class Layout(StrEnum):
    FILL = "fill"
    """The photo fills the frame; the camera moves over a part of it."""
    BLURRED = "blurred"
    """The whole photo over a blurred, enlarged copy of itself."""
    PAN = "pan"
    """A panorama, travelled from one end to the other."""


class Transition(StrEnum):
    CUT = "cut"
    DISSOLVE = "dissolve"
    FADE_BLACK = "fadeblack"


Rect = tuple[float, float, float, float]
"""x, y, width, height as shares of the photo."""


@dataclass(frozen=True)
class PlanPhoto:
    """A photo as the plan needs it: when and where it was taken, its look and embedding."""

    asset_id: UUID
    taken: datetime
    look: PhotoLook
    latitude: float | None = None
    longitude: float | None = None
    embedding: np.ndarray | None = field(default=None, compare=False, repr=False)

    @property
    def aspect(self) -> float:
        return self.look.width / max(1, self.look.height)


@dataclass(frozen=True)
class Shot:
    kind: str
    """"photo", "title" or "credits"."""
    start: float
    seconds: float
    """On screen from `start`, for `seconds`, the transition into it included."""
    transition: Transition
    transition_seconds: float
    asset_id: UUID | None = None
    layout: Layout | None = None
    move: tuple[Rect, Rect] | None = None
    """Where the camera looks at the start and at the end."""
    scene: int = 0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["asset_id"] = str(self.asset_id) if self.asset_id else None
        data["start"] = round(self.start, 3)
        data["seconds"] = round(self.seconds, 3)
        data["transition_seconds"] = round(self.transition_seconds, 3)
        if self.move is not None:
            data["move"] = [[round(v, 4) for v in rect] for rect in self.move]
        return data


@dataclass(frozen=True)
class Clip:
    album_id: UUID
    year: int
    part: int
    """1, 2… within the year; 0 when the year has one slideshow."""
    first: datetime
    last: datetime
    shots: tuple[Shot, ...]
    left_out: int
    """Photos of these months not shown: junk, near copies, too many in a scene."""
    title: str
    credits: bool

    @property
    def seconds(self) -> float:
        return max((s.start + s.seconds for s in self.shots), default=0.0)

    @property
    def photos(self) -> list[UUID]:
        return [s.asset_id for s in self.shots if s.asset_id is not None]

    def to_dict(self) -> dict[str, Any]:
        return {
            "v": PLAN_VERSION,
            "album_id": str(self.album_id),
            "year": self.year,
            "part": self.part,
            "first": self.first.isoformat(),
            "last": self.last.isoformat(),
            "title": self.title,
            "credits": self.credits,
            "left_out": self.left_out,
            "shots": [s.to_dict() for s in self.shots],
        }

    @property
    def version(self) -> str:
        data = json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True).encode()
        return f"show-{hashlib.sha256(data).hexdigest()[:32]}"


# --- the plan -------------------------------------------------------------------------------


def plan_album(
    album_id: UUID,
    title: str,
    photos: Sequence[PlanPhoto],
    *,
    seed: int = 0,
    credits: bool = True,
) -> list[Clip]:
    """The slideshows of an album: one per year (or several for a long year), oldest first."""
    clips: list[Clip] = []
    by_year: dict[int, list[PlanPhoto]] = {}
    for photo in sorted(photos, key=lambda p: (p.taken, str(p.asset_id))):
        by_year.setdefault(photo.taken.year, []).append(photo)
    for year, every in sorted(by_year.items()):
        chosen = [_choose(scene) for scene in scenes(every)]
        chosen = [scene for scene in chosen if scene]
        count = sum(len(scene) for scene in chosen)
        if count < MIN_PHOTOS:
            continue
        timed = [[(p, _seconds(p, len(scene), seed)) for p in scene] for scene in chosen]
        parts = _split(timed)
        starts = [min(p.taken for scene in part for p, _ in scene) for part in parts]
        for index, part in enumerate(parts, start=1):
            shown = {p.asset_id for scene in part for p, _ in scene}
            first = starts[index - 1]
            last = max(p.taken for scene in part for p, _ in scene)
            # A photo left out counts for the part it falls in: from the first photo of this part
            # (the beginning of the year for the first) to the first photo of the next.
            begin = first if index > 1 else datetime.min
            end = starts[index] if index < len(parts) else datetime.max
            span = [p for p in every if begin <= p.taken < end]
            clips.append(
                Clip(
                    album_id=album_id,
                    year=year,
                    part=index if len(parts) > 1 else 0,
                    first=first,
                    last=last,
                    shots=_shots(part, title, seed, credits),
                    left_out=sum(1 for p in span if p.asset_id not in shown),
                    title=title,
                    credits=credits,
                )
            )
    return clips


def scenes(photos: Sequence[PlanPhoto]) -> list[list[PlanPhoto]]:
    """Photos in the order of taking, cut where a pause or a move is long."""
    result: list[list[PlanPhoto]] = []
    for photo in sorted(photos, key=lambda p: (p.taken, str(p.asset_id))):
        if result:
            previous = result[-1][-1]
            gap = photo.taken - previous.taken
            moved = _km(previous, photo)
            if gap <= SCENE_GAP and (moved is None or moved <= SCENE_DISTANCE_KM):
                result[-1].append(photo)
                continue
        result.append([photo])
    return result


def _km(a: PlanPhoto, b: PlanPhoto) -> float | None:
    if None in (a.latitude, a.longitude, b.latitude, b.longitude):
        return None
    lat1, lon1, lat2, lon2 = map(
        math.radians,
        (a.latitude or 0.0, a.longitude or 0.0, b.latitude or 0.0, b.longitude or 0.0),
    )
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def _choose(scene: Sequence[PlanPhoto]) -> list[PlanPhoto]:
    """The photos of a scene that go into the slideshow, in the order of taking."""
    kept = [p for p in scene if p.embedding is None or not is_junk(p.embedding)]
    kept = [max(run, key=_score) for run in series(kept)]
    good = [p for p in kept if p.look.score >= POOR]
    if len(good) >= 3:
        kept = good
    if len(kept) > MAX_PER_SCENE:
        best = sorted(kept, key=lambda p: (-_score(p), str(p.asset_id)))[:MAX_PER_SCENE]
        keep = {p.asset_id for p in best}
        kept = [p for p in kept if p.asset_id in keep]
    return kept


def series(photos: Sequence[PlanPhoto]) -> list[list[PlanPhoto]]:
    """Runs of near copies taken one after another."""
    result: list[list[PlanPhoto]] = []
    for photo in photos:
        if result:
            last = result[-1][-1]
            if photo.taken - last.taken <= SERIES_WINDOW and _near_copies(last, photo):
                result[-1].append(photo)
                continue
        result.append([photo])
    return result


def _near_copies(a: PlanPhoto, b: PlanPhoto) -> bool:
    if a.embedding is not None and b.embedding is not None:
        return similarity(a.embedding, b.embedding) >= SERIES_SIMILARITY
    return (
        distance(a.look.phash, b.look.phash) <= SERIES_HASH_BITS
        and likeness(a.look.frame, b.look.frame) >= SERIES_LIKENESS
    )


def _score(photo: PlanPhoto) -> float:
    return photo.look.score


def _seconds(photo: PlanPhoto, scene_size: int, seed: int) -> float:
    seconds = PHOTO_SECONDS
    faces = len(photo.look.frame.faces)
    if faces >= 3:
        seconds += 0.5
    if photo.aspect >= PANORAMA:
        seconds += 1.0
    if scene_size >= BUSY_SCENE:
        seconds -= 0.5
    # A little unevenness, the same every time: a rhythm that is not mechanical.
    seconds += (_unit(photo.asset_id, seed, "t") - 0.5) * 0.5
    return min(MAX_SECONDS, max(MIN_SECONDS, seconds))


def _unit(asset_id: UUID, seed: int, salt: str) -> float:
    digest = hashlib.sha256(f"{asset_id}/{seed}/{salt}".encode()).digest()
    return int.from_bytes(digest[:4], "big") / 2**32


Timed = list[list[tuple[PlanPhoto, float]]]
"""Scenes of photos with their seconds."""


def _split(scenes_: Timed) -> list[Timed]:
    """The scenes of a year, in parts of at most CLIP_MAX_SECONDS, cut between scenes (a scene
    too long for one part is cut too). The parts are about equal."""
    extra = TITLE_SECONDS + CREDITS_SECONDS
    units: Timed = []
    for scene in scenes_:
        chunk: list[tuple[PlanPhoto, float]] = []
        for item in scene:
            if chunk and sum(s for _, s in chunk) + item[1] > CLIP_TARGET_SECONDS:
                units.append(chunk)
                chunk = []
            chunk.append(item)
        units.append(chunk)
    total = sum(s for unit in units for _, s in unit)
    if total + extra <= CLIP_MAX_SECONDS:
        return [units]
    count = math.ceil(total / CLIP_TARGET_SECONDS)
    target = total / count
    parts: list[Timed] = [[]]
    for unit in units:
        seconds = sum(s for _, s in unit)
        current = sum(s for u in parts[-1] for _, s in u)
        # A new part when this one has its share and the unit would take it past the target
        # by more than half of the unit.
        if parts[-1] and current + seconds / 2 > target and len(parts) < count:
            parts.append([])
        parts[-1].append(unit)
    return parts


def _shots(part: Timed, title: str, seed: int, credits: bool) -> tuple[Shot, ...]:
    shots: list[Shot] = [
        Shot("title", 0.0, TITLE_SECONDS, Transition.CUT, 0.0, scene=0),
    ]
    end = TITLE_SECONDS
    index = 0
    previous: PlanPhoto | None = None
    for scene_number, scene in enumerate(part, start=1):
        for position, (photo, seconds) in enumerate(scene):
            if previous is None or position == 0:
                transition, overlap = Transition.FADE_BLACK, FADE_BLACK_SECONDS
            else:
                transition, overlap = Transition.DISSOLVE, _dissolve(previous, photo)
            start = end - overlap
            layout, move = camera(photo, index, seed)
            shots.append(
                Shot(
                    "photo",
                    start,
                    seconds + overlap,
                    transition,
                    overlap,
                    asset_id=photo.asset_id,
                    layout=layout,
                    move=move,
                    scene=scene_number,
                )
            )
            end = start + seconds + overlap
            previous = photo
            index += 1
    if credits:
        shots.append(
            Shot(
                "credits",
                end - FADE_BLACK_SECONDS,
                CREDITS_SECONDS + FADE_BLACK_SECONDS,
                Transition.FADE_BLACK,
                FADE_BLACK_SECONDS,
                scene=len(part) + 1,
            )
        )
    return tuple(shots)


def _dissolve(a: PlanPhoto, b: PlanPhoto) -> float:
    if a.embedding is not None and b.embedding is not None:
        alike = (similarity(a.embedding, b.embedding) - 0.6) / 0.35
    else:
        alike = (likeness(a.look.frame, b.look.frame) - 0.7) / 0.3
    alike = min(1.0, max(0.0, alike))
    return DISSOLVE_MIN + (DISSOLVE_MAX - DISSOLVE_MIN) * alike


# --- the camera ------------------------------------------------------------------------------


def camera(photo: PlanPhoto, index: int, seed: int = 0) -> tuple[Layout, tuple[Rect, Rect]]:
    """How the camera moves over a photo: its layout, and where it looks at the start and the
    end. The faces (or the region kept for them) stay in view at both ends."""
    aspect = photo.aspect
    point = photo.look.frame.point
    region = photo.look.frame.region
    zoom_in = (index + seed) % 2 == 0
    if aspect < STANDING:
        whole: Rect = (0.0, 0.0, 1.0, 1.0)
        near = _around(point, 1 / STANDING_ZOOM, 1 / STANDING_ZOOM, region)
        return Layout.BLURRED, (whole, near) if zoom_in else (near, whole)
    if aspect >= PANORAMA:
        width = min(1.0, ASPECT / aspect)
        left: Rect = (0.0, 0.0, width, 1.0)
        right: Rect = (1.0 - width, 0.0, width, 1.0)
        forward = _unit(photo.asset_id, seed, "pan") < 0.5
        return Layout.PAN, (left, right) if forward else (right, left)
    # The largest frame of 16:9 in the photo, and a smaller one around the point of interest.
    if aspect >= ASPECT:
        base_w, base_h = ASPECT / aspect, 1.0
    else:
        base_w, base_h = 1.0, aspect / ASPECT
    zoom = ZOOM
    if region is not None:
        # Not so close that the faces no longer fit.
        fit = min(base_w / max(region[2], 1e-6), base_h / max(region[3], 1e-6))
        zoom = max(1.0, min(ZOOM, fit))
    wide = _around(point, base_w, base_h, region)
    if zoom < MIN_ZOOM:
        # No room to come closer without cutting the faces: travel along the photo instead,
        # as far as the faces allow.
        return Layout.FILL, _glide(wide, region, forward=zoom_in)
    close = _around(point, base_w / zoom, base_h / zoom, region)
    return Layout.FILL, (wide, close) if zoom_in else (close, wide)


def _glide(frame: Rect, region: Rect | None, *, forward: bool) -> tuple[Rect, Rect]:
    """Two frames of the same size, apart along the longer free side of the photo, both holding
    the region. The same frame twice when there is no room."""
    x, y, w, h = frame
    rx, ry, rw, rh = region if region is not None else (x, y, w, h)
    # Along a side the region does not fit, it can not be held anyway: the whole side is free.
    lo_x, hi_x = (max(0.0, rx + rw - w), min(1.0 - w, rx)) if rw <= w else (0.0, 1.0 - w)
    lo_y, hi_y = (max(0.0, ry + rh - h), min(1.0 - h, ry)) if rh <= h else (0.0, 1.0 - h)
    room_x, room_y = max(0.0, hi_x - lo_x), max(0.0, hi_y - lo_y)
    if room_x <= 1e-6 and room_y <= 1e-6:
        return frame, frame
    if room_x >= room_y:
        travel = min(room_x, GLIDE * w)
        middle = min(max(x, lo_x + travel / 2), hi_x - travel / 2)
        a: Rect = (middle - travel / 2, y, w, h)
        b: Rect = (middle + travel / 2, y, w, h)
    else:
        travel = min(room_y, GLIDE * h)
        middle = min(max(y, lo_y + travel / 2), hi_y - travel / 2)
        a = (x, middle - travel / 2, w, h)
        b = (x, middle + travel / 2, w, h)
    return (a, b) if forward else (b, a)


def _around(point: tuple[float, float], width: float, height: float, region: Rect | None) -> Rect:
    """A frame of this size centred on the point as far as it can be, inside the photo, and
    holding the region when the region fits."""
    cx, cy = point
    if region is not None and region[2] <= width and region[3] <= height:
        # Move the centre just enough for the region to be inside.
        rx, ry, rw, rh = region
        cx = min(max(cx, rx + rw - width / 2), rx + width / 2)
        cy = min(max(cy, ry + rh - height / 2), ry + height / 2)
    x = min(max(cx - width / 2, 0.0), 1.0 - width)
    y = min(max(cy - height / 2, 0.0), 1.0 - height)
    return (x, y, width, height)


__all__ = [
    "Clip",
    "Layout",
    "PlanPhoto",
    "Shot",
    "Transition",
    "camera",
    "plan_album",
    "scenes",
    "series",
]
