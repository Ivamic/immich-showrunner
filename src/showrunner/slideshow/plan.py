# SPDX-License-Identifier: AGPL-3.0-or-later
"""The cut list of a slideshow: which photos, in what order, for how long, how the camera moves
over each and how one gives way to the next. Pure logic and deterministic: the same photos give
the same list, and the version of a list (a hash of it) says when a slideshow is to be made again.

The rules (see D-091, D-097, D-106):

- one slideshow per year, of 3 to 5 minutes; a long year is cut into parts of whole days, never
  within a day, and is at most half an hour in all;
- the order is the time of taking; a scene ends with the day, after a pause of more than two
  hours or a move of more than about 20 km;
- screenshots, documents and receipts are left out; a series of near copies becomes its best
  photo; a day gives about twice the square root of its photos left (a busy day more, but not all
  of them), shared among its scenes by their size;
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
from itertools import pairwise
from typing import Any
from uuid import UUID

import numpy as np

from showrunner.artwork.select import likeness
from showrunner.slideshow.content import is_junk
from showrunner.slideshow.embed import similarity
from showrunner.slideshow.photos import PhotoLook, distance

PLAN_VERSION = 3
"""Raised when the rules change, so that every slideshow is made again (2: a series is measured
against its first photo, not the one before; 3: a share for each day, parts of whole days)."""
ASPECT = 16 / 9

SCENE_GAP = timedelta(hours=2)
SCENE_DISTANCE_KM = 20.0
SERIES_WINDOW = timedelta(minutes=15)
SERIES_GAP = timedelta(minutes=2)
SERIES_SIMILARITY = 0.92
"""A photo this alike to the first of a series, taken at most SERIES_GAP after the one before and
within SERIES_WINDOW of the first, belongs to it: only the best of a series stays."""
SERIES_HASH_BITS = 10
SERIES_LIKENESS = 0.9
"""Without embeddings: hashes this close and colours this alike make a series."""
DAY_SHARE = 2.0
"""A day gives about DAY_SHARE x sqrt(n) photos of the n left after near copies and junk."""
DAY_ALL = 8
"""A day with at most this many photos left shows them all."""
DAY_MAX_PHOTOS = 55
"""At most, so that a day fits in one part."""
YEAR_MAX_SECONDS = 1800.0
"""A year is at most half an hour in all; the shares of its days shrink alike to fit."""
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

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Shot:
        move = data.get("move")
        return cls(
            kind=data["kind"],
            start=float(data["start"]),
            seconds=float(data["seconds"]),
            transition=Transition(data["transition"]),
            transition_seconds=float(data["transition_seconds"]),
            asset_id=UUID(data["asset_id"]) if data.get("asset_id") else None,
            layout=Layout(data["layout"]) if data.get("layout") else None,
            move=(_rect(move[0]), _rect(move[1])) if move else None,
            scene=int(data.get("scene", 0)),
        )


@dataclass(frozen=True)
class AudioPart:
    """A stretch of a piece of music under the slideshow."""

    track: str
    """The piece: its id in the music set, or the name of the user's file."""
    source_start: float
    """Where in the piece it begins, seconds."""
    at: float
    """Where in the slideshow it begins."""
    seconds: float
    fade_in: float
    fade_out: float
    gain_db: float
    """Brings the piece to the loudness of slideshows."""

    def to_dict(self) -> dict[str, Any]:
        return {k: (round(v, 3) if isinstance(v, float) else v) for k, v in asdict(self).items()}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AudioPart:
        return cls(
            track=str(data["track"]),
            **{k: float(data[k]) for k in ("source_start", "at", "seconds", "fade_in", "fade_out")},
            gain_db=float(data["gain_db"]),
        )


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
    music: tuple[AudioPart, ...] = ()
    music_credits: tuple[str, ...] = ()
    """Who made the music and under which licence, a line a piece."""
    report: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)
    """Why photos were left out (`_report`): for the page only, not in the cut list."""

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
            "music": [m.to_dict() for m in self.music],
            "music_credits": list(self.music_credits),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Clip:
        return cls(
            album_id=UUID(data["album_id"]),
            year=int(data["year"]),
            part=int(data["part"]),
            first=datetime.fromisoformat(data["first"]),
            last=datetime.fromisoformat(data["last"]),
            shots=tuple(Shot.from_dict(s) for s in data["shots"]),
            left_out=int(data["left_out"]),
            title=data["title"],
            credits=bool(data["credits"]),
            music=tuple(AudioPart.from_dict(m) for m in data.get("music", [])),
            music_credits=tuple(data.get("music_credits", [])),
        )

    @property
    def caption(self) -> str:
        """The text of the title: the album and the year, and the months of a part."""
        if self.part:
            return f"{self.title} · {self.year} · {self.first:%m}-{self.last:%m}"
        return f"{self.title} · {self.year}"

    @property
    def version(self) -> str:
        data = json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True).encode()
        return f"show-{hashlib.sha256(data).hexdigest()[:32]}"


def _rect(values: Sequence[float]) -> Rect:
    return (float(values[0]), float(values[1]), float(values[2]), float(values[3]))


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
        fates: dict[UUID, str] = {}
        cut: list[list[PlanPhoto]] = []
        kept_days: list[list[list[PlanPhoto]]] = []
        for one_day in _days(every):
            day_scenes = scenes(one_day)
            cut += day_scenes
            kept = [_keep(scene, fates) for scene in day_scenes]
            kept_days.append([scene for scene in kept if scene])
        shares = _shares([sum(len(s) for s in d) for d in kept_days])
        chosen_days = [_pick(d, share, fates) for d, share in zip(kept_days, shares, strict=True)]
        chosen_days = [d for d in chosen_days if d]
        count = sum(len(scene) for d in chosen_days for scene in d)
        if count < MIN_PHOTOS:
            continue
        timed = [
            [[(p, _seconds(p, len(scene), seed)) for p in scene] for scene in d]
            for d in chosen_days
        ]
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
                    report=_report(span, shown, fates, sum(1 for s in cut if s[0] in span)),
                )
            )
    return clips


def _report(
    span: Sequence[PlanPhoto], shown: set[UUID], fates: dict[UUID, str], scene_count: int
) -> dict[str, Any]:
    """Why the photos of a slideshow were left out, in all and day by day (for the page; not
    part of the cut list, so it draws nothing again)."""
    reasons: dict[str, int] = {}
    days: dict[str, dict[str, int]] = {}
    for p in span:
        fate = "shown" if p.asset_id in shown else fates.get(p.asset_id, "other")
        day = days.setdefault(f"{p.taken:%Y-%m-%d}", {"photos": 0})
        day["photos"] += 1
        day[fate] = day.get(fate, 0) + 1
        if fate != "shown":
            reasons[fate] = reasons.get(fate, 0) + 1
    return {
        "reasons": reasons,
        "scenes": scene_count,
        "days": [{"date": d, **counts} for d, counts in sorted(days.items())],
    }


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


def _days(photos: Sequence[PlanPhoto]) -> list[list[PlanPhoto]]:
    """The photos (in the order of taking) by the day they were taken."""
    result: dict[object, list[PlanPhoto]] = {}
    for photo in photos:
        result.setdefault(photo.taken.date(), []).append(photo)
    return list(result.values())


def _shares(sizes: Sequence[int]) -> list[int]:
    """How many photos each day gives, of the `sizes` left after near copies and junk: all of a
    few (DAY_ALL), else about DAY_SHARE x sqrt(n), at most DAY_MAX_PHOTOS; all shrunk alike
    when the year would be too long."""
    shares = [min(n, DAY_MAX_PHOTOS, max(DAY_ALL, round(DAY_SHARE * math.sqrt(n)))) for n in sizes]
    limit = int(YEAR_MAX_SECONDS / PHOTO_SECONDS)
    total = sum(shares)
    if total > limit:
        shares = [max(1, math.floor(s * limit / total)) if s else 0 for s in shares]
    return shares


def _pick(
    day_scenes: Sequence[Sequence[PlanPhoto]], share: int, fates: dict[UUID, str]
) -> list[list[PlanPhoto]]:
    """The best photos of a day, `share` of them, shared among its scenes by their size (each
    scene one at least, while there are enough); in the order of taking. The rest are noted as
    "scene" (over the share)."""
    counts = [0] * len(day_scenes)
    # Every scene its first photo, the largest scenes first when there are too few.
    order = sorted(range(len(day_scenes)), key=lambda i: (-len(day_scenes[i]), i))
    for i in order[:share]:
        counts[i] = 1
    # The rest in proportion to the size of the scenes (highest averages).
    for _ in range(share - sum(counts)):
        free = [i for i in range(len(day_scenes)) if counts[i] < len(day_scenes[i])]
        if not free:
            break
        best = max(free, key=lambda i: (len(day_scenes[i]) / (counts[i] + 1), -i))
        counts[best] += 1
    result = []
    for scene, count in zip(day_scenes, counts, strict=True):
        best_ones = sorted(scene, key=lambda p: (-_score(p), str(p.asset_id)))[:count]
        keep = {p.asset_id for p in best_ones}
        for p in scene:
            if p.asset_id not in keep:
                fates[p.asset_id] = "scene"
        if keep:
            result.append([p for p in scene if p.asset_id in keep])
    return result


def _keep(scene: Sequence[PlanPhoto], fates: dict[UUID, str] | None = None) -> list[PlanPhoto]:
    """The photos of a scene that may go into the slideshow, in the order of taking: without
    junk, near copies and (when there are better ones) poor photos. `fates` learns why each
    photo left out was left out: "junk", "series" or "poor"."""
    fate = fates if fates is not None else {}
    kept = []
    for p in scene:
        if p.embedding is not None and is_junk(p.embedding):
            fate[p.asset_id] = "junk"
        else:
            kept.append(p)
    runs = series(kept)
    kept = [max(run, key=_score) for run in runs]
    for run, kept_one in zip(runs, kept, strict=True):
        for p in run:
            if p is not kept_one:
                fate[p.asset_id] = "series"
    good = [p for p in kept if p.look.score >= POOR]
    if len(good) >= 3:
        for p in kept:
            if p.look.score < POOR:
                fate[p.asset_id] = "poor"
        kept = good
    return kept


def series(photos: Sequence[PlanPhoto]) -> list[list[PlanPhoto]]:
    """Runs of near copies taken one after another. Each photo is measured against the first of
    its run: compared with the one before, a walk where every photo looks like the last would
    become one run, and a whole day one photo."""
    result: list[list[PlanPhoto]] = []
    for photo in photos:
        if result:
            run = result[-1]
            first, last = run[0], run[-1]
            if (
                photo.taken - last.taken <= SERIES_GAP
                and photo.taken - first.taken <= SERIES_WINDOW
                and _near_copies(first, photo)
            ):
                run.append(photo)
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


def _split(days: Sequence[Timed]) -> list[Timed]:
    """The days of a year (each its scenes) in parts of whole days, about equal and each at most
    CLIP_MAX_SECONDS where the days allow it; a day is never cut."""
    extra = TITLE_SECONDS + CREDITS_SECONDS
    lengths = [sum(s for scene in d for _, s in scene) for d in days]
    total = sum(lengths)
    if total + extra <= CLIP_MAX_SECONDS or len(days) == 1:
        return [[scene for d in days for scene in d]]
    fits = CLIP_MAX_SECONDS - extra
    cuts: list[int] | None = None
    count = max(2, math.ceil(total / CLIP_TARGET_SECONDS))
    while cuts is None and count < len(days):
        cuts = _balanced(lengths, count, fits)
        count += 1
    if cuts is None:
        cuts = list(range(1, len(days)))
    bounds = [0, *cuts, len(days)]
    return [[scene for d in days[a:b] for scene in d] for a, b in pairwise(bounds)]


def _balanced(lengths: Sequence[float], count: int, fits: float) -> list[int] | None:
    """Where to cut `lengths` (in order) into `count` runs, none longer than `fits`, as equal as
    can be (least sum of squares off the mean); None when they do not fit."""
    n = len(lengths)
    prefix = [0.0]
    for length in lengths:
        prefix.append(prefix[-1] + length)
    mean = prefix[-1] / count
    inf = float("inf")
    # cost[k][i]: the best for the first i days in k runs; back[k][i]: where the last run starts.
    cost = [[inf] * (n + 1) for _ in range(count + 1)]
    back = [[0] * (n + 1) for _ in range(count + 1)]
    cost[0][0] = 0.0
    for k in range(1, count + 1):
        for i in range(k, n - (count - k) + 1):
            for j in range(i - 1, k - 2, -1):
                run = prefix[i] - prefix[j]
                if run > fits:
                    break
                if cost[k - 1][j] < inf:
                    value = cost[k - 1][j] + (run - mean) ** 2
                    if value < cost[k][i]:
                        cost[k][i], back[k][i] = value, j
    if cost[count][n] == inf:
        return None
    cuts: list[int] = []
    i = n
    for _ in range(count):
        i = back[count - len(cuts)][i]
        cuts.append(i)
    return sorted(cuts)[1:]


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
    "AudioPart",
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
