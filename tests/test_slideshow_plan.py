# SPDX-License-Identifier: AGPL-3.0-or-later
"""The cut list of a slideshow: scenes, near copies and junk left out, a year in parts of at most
five minutes, a timeline without gaps, and a camera that keeps the faces in view."""

import itertools
import random
from datetime import datetime, timedelta
from uuid import UUID

import numpy as np
import pytest

from fake_immich import album_id, asset_id
from showrunner.artwork.faces import Face
from showrunner.artwork.quality import Quality
from showrunner.artwork.select import FrameLook
from showrunner.slideshow.content import prompts, shares
from showrunner.slideshow.photos import PhotoLook
from showrunner.slideshow.plan import (
    ASPECT,
    CLIP_MAX_SECONDS,
    CREDITS_SECONDS,
    TITLE_SECONDS,
    YEAR_MAX_SECONDS,
    Layout,
    PlanPhoto,
    Transition,
    camera,
    plan_album,
    scenes,
)

START = datetime(2024, 7, 1, 9, 0)
ALBUM = album_id(1)


def look(
    n: int,
    *,
    size: tuple[int, int] = (1280, 960),
    score: float = 0.7,
    faces: tuple[Face, ...] = (),
    point: tuple[float, float] = (0.5, 0.5),
    region: tuple[float, float, float, float] | None = None,
    phash: int | None = None,
) -> PhotoLook:
    rng = random.Random(n)
    frame = FrameLook(
        asset_id=str(asset_id(n)),
        at=0.0,
        quality=Quality(0.8, 0.8, 0.8, 0.5, 0.0, max(size), score),
        faces=faces,
        point=point,
        region=region,
        signature=tuple(rng.randrange(256) for _ in range(12 * 12 * 3)),
    )
    return PhotoLook(
        frame=frame,
        width=size[0],
        height=size[1],
        given_side=max(size),
        phash=phash if phash is not None else rng.getrandbits(63),
    )


def vector(seed: int) -> np.ndarray:
    """An embedding near one of the words of photos (never junk), unlike its neighbours."""
    rng = np.random.default_rng(seed)
    photo_words = prompts().vectors[[g == "photo" for g in prompts().groups]]
    noise = 0.01 * rng.standard_normal(512).astype(np.float32)
    v: np.ndarray = photo_words[seed % len(photo_words)] + noise
    return v / float(np.linalg.norm(v))


def photo(
    n: int,
    minutes: float,
    *,
    where: tuple[float, float] | None = None,
    embedding: np.ndarray | None = None,
    **kw: object,
) -> PlanPhoto:
    return PlanPhoto(
        asset_id=asset_id(n),
        taken=START + timedelta(minutes=minutes),
        look=look(n, **kw),  # type: ignore[arg-type]
        latitude=where[0] if where else None,
        longitude=where[1] if where else None,
        embedding=vector(n) if embedding is None else embedding,
    )


def day(first: int, count: int, start_minutes: float = 0, step: float = 20) -> list[PlanPhoto]:
    return [photo(first + i, start_minutes + i * step) for i in range(count)]


# --- scenes and choice ---------------------------------------------------------------------


def test_scenes_are_cut_by_pauses_and_by_moves() -> None:
    photos = [
        photo(1, 0, where=(43.70, 7.26)),
        photo(2, 30, where=(43.71, 7.27)),  # a kilometre further, half an hour later
        photo(3, 60, where=(45.83, 6.86)),  # 250 km: another place
        photo(4, 90),  # no GPS: only time counts
        photo(5, 90 + 181),  # three hours later
    ]
    cut = scenes(photos)
    assert [[p.asset_id for p in s] for s in cut] == [
        [asset_id(1), asset_id(2)],
        [asset_id(3), asset_id(4)],
        [asset_id(5)],
    ]


def test_a_series_of_near_copies_becomes_its_best_photo() -> None:
    same = vector(100)
    burst = [
        photo(1, 0, embedding=same, score=0.5),
        photo(2, 0.1, embedding=same, score=0.9),
        photo(3, 0.2, embedding=same, score=0.6),
    ]
    others = day(10, 6, start_minutes=1)
    (clip,) = plan_album(ALBUM, "Trip", burst + others)
    assert asset_id(2) in clip.photos
    assert asset_id(1) not in clip.photos and asset_id(3) not in clip.photos
    assert clip.left_out == 2


def test_without_embeddings_near_copies_are_told_by_hash_and_colour() -> None:
    a = photo(1, 0, phash=0b1011 << 40, score=0.4)
    b = PlanPhoto(
        asset_id=asset_id(2),
        taken=START + timedelta(seconds=5),
        look=PhotoLook(
            frame=FrameLook(**{**a.look.frame.__dict__, "asset_id": str(asset_id(2))}),
            width=1280,
            height=960,
            given_side=1280,
            phash=(0b1011 << 40) ^ 0b111,  # three bits apart
        ),
    )
    a = PlanPhoto(a.asset_id, a.taken, a.look)  # no embedding either
    others = [PlanPhoto(p.asset_id, p.taken, p.look) for p in day(10, 6, start_minutes=1)]
    (clip,) = plan_album(ALBUM, "Trip", [a, b, *others])
    assert (asset_id(1) in clip.photos) != (asset_id(2) in clip.photos)


def test_screenshots_and_documents_are_left_out() -> None:
    words = prompts()
    screenshot = words.vectors[words.texts.index("a screenshot of a phone screen")]
    assert shares(screenshot)["junk"] > 0.9
    photos = [*day(1, 6), photo(50, 3, embedding=screenshot)]
    (clip,) = plan_album(ALBUM, "Trip", photos)
    assert asset_id(50) not in clip.photos
    assert len(clip.photos) == 6


def test_a_year_with_too_few_photos_gets_no_slideshow() -> None:
    assert plan_album(ALBUM, "Trip", day(1, 5)) == []


def test_a_day_gives_about_twice_the_square_root_of_its_photos_the_best_ones() -> None:
    photos = [photo(i, i * 5, score=0.3 + i / 100) for i in range(1, 21)]
    (clip,) = plan_album(ALBUM, "Trip", photos)
    assert len(clip.photos) == 9, "2 x sqrt(20)"
    assert clip.photos == [asset_id(i) for i in range(12, 21)], "the best, in the order of taking"


def test_a_busy_day_gives_more_but_not_all_of_its_photos() -> None:
    busy = [photo(i, i * 5, score=0.5 + (i % 7) / 100) for i in range(1, 101)]
    quiet = [photo(200 + i, 24 * 60 + i * 20) for i in range(8)]
    (clip,) = plan_album(ALBUM, "Trip", busy + quiet)
    shown = set(clip.photos)
    assert len(shown & {p.asset_id for p in busy}) == 20
    assert len(shown & {p.asset_id for p in quiet}) == 8, "a few are all shown"
    assert clip.report["days"][0]["scene"] == 80


def test_the_share_of_a_day_goes_to_each_of_its_scenes_by_their_size() -> None:
    morning = [photo(i, i * 5) for i in range(1, 31)]
    evening = [photo(100 + i, 10 * 60 + i * 5) for i in range(10)]  # after a long pause
    (clip,) = plan_album(ALBUM, "Trip", morning + evening)
    shown = set(clip.photos)
    from_morning = len(shown & {p.asset_id for p in morning})
    from_evening = len(shown & {p.asset_id for p in evening})
    assert from_morning + from_evening == 13, "2 x sqrt(40)"
    assert from_evening >= 2 and from_morning > from_evening


# --- the year in parts ------------------------------------------------------------------------


def test_a_long_year_is_cut_into_parts_of_at_most_five_minutes() -> None:
    photos: list[PlanPhoto] = []
    for d in range(20):  # twenty days of six photos shown: about 7 minutes
        photos += day(1000 + d * 10, 10, start_minutes=d * 24 * 60)
    clips = plan_album(ALBUM, "Summer", photos)
    assert len(clips) >= 2
    assert [c.part for c in clips] == list(range(1, len(clips) + 1))
    for clip in clips:
        assert 120 <= clip.seconds <= CLIP_MAX_SECONDS + 5, clip.seconds
    shown = [p for c in clips for p in c.photos]
    assert len(shown) == len(set(shown)), "each photo in one part"
    assert clips[0].last < clips[1].first, "parts follow each other in time"


def test_a_day_is_never_cut_between_parts() -> None:
    photos: list[PlanPhoto] = []
    for d, count in enumerate([254, 206, 616, 639, 595, 117]):  # a trip of six days
        photos += [photo(10000 * (d + 1) + i, d * 24 * 60 + i * 1.3) for i in range(count)]
    clips = plan_album(ALBUM, "Trip", photos)
    assert len(clips) >= 2
    days_of = [{p.taken.date() for p in photos if p.asset_id in set(c.photos)} for c in clips]
    for a, b in itertools.pairwise(days_of):
        assert not a & b, "a day in one part only"
    for clip in clips:
        assert clip.seconds <= CLIP_MAX_SECONDS + 5, clip.seconds
    longest, shortest = max(c.seconds for c in clips), min(c.seconds for c in clips)
    assert longest - shortest < 120, [c.seconds for c in clips]


def test_a_year_is_at_most_half_an_hour() -> None:
    photos: list[PlanPhoto] = []
    for d in range(100):  # a hundred busy days
        photos += [photo(100000 + d * 100 + i, d * 24 * 60 + i * 5) for i in range(60)]
    clips = plan_album(ALBUM, "Year", photos)
    extra = TITLE_SECONDS + CREDITS_SECONDS
    assert sum(c.seconds - extra for c in clips) <= YEAR_MAX_SECONDS + 30
    days_shown = {
        p.taken.date() for p in photos if p.asset_id in {a for c in clips for a in c.photos}
    }
    assert len(days_shown) == 100, "every day still has its place"


def test_one_slideshow_per_year_and_part_zero_when_there_is_one() -> None:
    photos = day(1, 8) + [photo(100 + i, 365 * 24 * 60 + i * 20) for i in range(8)]
    clips = plan_album(ALBUM, "Two years", photos)
    assert [(c.year, c.part) for c in clips] == [(2024, 0), (2025, 0)]


def test_the_plan_is_the_same_every_time_and_follows_the_photos() -> None:
    photos = day(1, 10)
    (a,) = plan_album(ALBUM, "Trip", photos)
    (b,) = plan_album(ALBUM, "Trip", list(reversed(photos)))
    assert a.version == b.version
    (c,) = plan_album(ALBUM, "Trip", [*photos, photo(99, 300)])
    assert c.version != a.version
    (d,) = plan_album(ALBUM, "Trip", photos, seed=1)
    assert d.version != a.version, "another seed: another plan"


# --- the timeline -----------------------------------------------------------------------------


def test_the_timeline_has_no_gaps_and_starts_and_ends_well() -> None:
    photos = day(1, 4) + day(10, 4, start_minutes=600)  # two scenes
    (clip,) = plan_album(ALBUM, "Trip", photos)
    kinds = [s.kind for s in clip.shots]
    assert kinds[0] == "title" and kinds[-1] == "credits"
    for before, after in zip(clip.shots, clip.shots[1:], strict=False):
        end = before.start + before.seconds
        assert after.start == pytest.approx(end - after.transition_seconds)
    photo_shots = [s for s in clip.shots if s.kind == "photo"]
    first_of_scene = [s for s in photo_shots if s.transition is Transition.FADE_BLACK]
    assert [s.asset_id for s in first_of_scene] == [asset_id(1), asset_id(10)]
    assert all(s.transition is Transition.DISSOLVE for s in photo_shots if s not in first_of_scene)
    for s in photo_shots:
        assert 3.0 <= s.seconds - s.transition_seconds <= 5.0


def test_alike_photos_dissolve_longer() -> None:
    base = vector(7)
    near = base + 0.25 * vector(8)
    near /= np.linalg.norm(near)
    alike = [photo(1, 0, embedding=base), photo(2, 20, embedding=near)]
    unlike = [photo(1, 0, embedding=vector(3)), photo(2, 20, embedding=-vector(3))]
    rest = day(10, 5, start_minutes=600)
    (a,) = plan_album(ALBUM, "T", alike + rest)
    (b,) = plan_album(ALBUM, "T", unlike + rest)
    assert a.shots[2].transition_seconds > b.shots[2].transition_seconds


def test_without_credits_the_slideshow_ends_on_a_photo() -> None:
    (clip,) = plan_album(ALBUM, "Trip", day(1, 8), credits=False)
    assert clip.shots[-1].kind == "photo"


# --- the camera -------------------------------------------------------------------------------


def inside(inner: tuple[float, ...], outer: tuple[float, ...]) -> bool:
    ix, iy, iw, ih = inner
    ox, oy, ow, oh = outer
    eps = 1e-6
    return (
        ox - eps <= ix and oy - eps <= iy and ix + iw <= ox + ow + eps and iy + ih <= oy + oh + eps
    )


WHOLE = (0.0, 0.0, 1.0, 1.0)


def test_the_camera_keeps_the_faces_in_view_and_zooms_in_and_out_in_turn() -> None:
    region = (0.70, 0.20, 0.22, 0.40)  # faces near the right edge
    p = photo(1, 0, size=(1600, 1200), point=(0.8, 0.4), region=region)
    layout, (start, end) = camera(p, 0)
    assert layout is Layout.FILL
    for rect in (start, end):
        assert inside(rect, WHOLE)
        assert inside(region, rect), rect
        assert rect[2] * 1600 / (rect[3] * 1200) == pytest.approx(ASPECT)
    assert end[2] < start[2], "the first photo zooms in"
    _, (start2, end2) = camera(p, 1)
    assert end2[2] > start2[2], "the next zooms out"


def test_faces_too_large_for_a_close_frame_lower_the_zoom() -> None:
    region = (0.05, 0.05, 0.9, 0.62)
    p = photo(1, 0, size=(1920, 1080), point=(0.5, 0.4), region=region)
    _, (wide, close) = camera(p, 0)
    assert inside(region, close) and inside(region, wide)


def test_with_no_room_to_come_closer_the_camera_glides_and_keeps_the_faces() -> None:
    region = (0.30, 0.02, 0.40, 0.97)  # a tall face: no closer frame holds it
    p = photo(1, 0, size=(2000, 1000), point=(0.5, 0.5), region=region)
    _, (start, end) = camera(p, 0)
    assert start != end, "the camera moves"
    assert start[2:] == end[2:], "the same size: it glides"
    for rect in (start, end):
        assert inside(region, rect) and inside(rect, WHOLE)


def test_a_standing_photo_is_shown_whole_and_a_panorama_travelled() -> None:
    standing = photo(1, 0, size=(960, 1280))
    layout, (start, end) = camera(standing, 0)
    assert layout is Layout.BLURRED
    assert start == WHOLE and inside(end, WHOLE)
    panorama = photo(2, 0, size=(6000, 1500))
    layout, (start, end) = camera(panorama, 0)
    assert layout is Layout.PAN
    assert start[3] == end[3] == 1.0
    assert sorted([start[0], end[0]]) == pytest.approx([0.0, 1.0 - start[2]])


def test_the_cut_list_is_plain_data() -> None:
    (clip,) = plan_album(ALBUM, "Trip", day(1, 8))
    data = clip.to_dict()
    assert data["v"] >= 1 and data["album_id"] == str(ALBUM)
    assert isinstance(data["shots"][1]["move"], list)
    assert UUID(data["shots"][1]["asset_id"]) == asset_id(1)


def test_a_cut_list_comes_back_from_its_data() -> None:
    from showrunner.slideshow.plan import Clip

    (clip,) = plan_album(ALBUM, "Trip", day(1, 8))
    again = Clip.from_dict(clip.to_dict())
    assert again.to_dict() == clip.to_dict()
    assert again.version == clip.version
    assert clip.caption == "Trip · 2024"


def test_the_report_says_why_each_photo_was_left_out_day_by_day() -> None:
    words = prompts()
    screenshot = words.vectors[words.texts.index("a screenshot of a phone screen")]
    same = vector(200)
    photos = [
        photo(1, 0, embedding=same, score=0.9),
        photo(2, 0.1, embedding=same, score=0.5),  # a near copy of 1
        photo(3, 1, embedding=screenshot),  # junk
        *[photo(10 + i, 2 + i * 5, score=0.3 + i / 100) for i in range(14)],  # 7 over the share
        *[photo(40 + i, 24 * 60 + i * 20) for i in range(6)],  # the next day
    ]
    (clip,) = plan_album(ALBUM, "Trip", photos)
    report = clip.report
    assert report["reasons"] == {"series": 1, "junk": 1, "scene": 7}
    assert sum(report["reasons"].values()) == clip.left_out
    first, second = report["days"]
    assert first["date"] == "2024-07-01" and first["photos"] == 17
    assert first["shown"] + first["series"] + first["junk"] + first["scene"] == 17
    assert second == {"date": "2024-07-02", "photos": 6, "shown": 6}
    assert "report" not in clip.to_dict(), "not part of the cut list: nothing is drawn again"


def test_a_walk_of_photos_each_like_the_one_before_is_not_one_series() -> None:
    from showrunner.slideshow.plan import series

    # Each photo drifts a little from the one before: alike to its neighbour, not to the first.
    rng = np.random.default_rng(5)
    v = vector(300)
    walk = []
    for i in range(12):
        walk.append(photo(500 + i, i * 1.0, embedding=v.copy()))
        step = rng.standard_normal(512).astype(np.float32)
        v = v + 0.3 * step / float(np.linalg.norm(step))
        v = v / float(np.linalg.norm(v))
    runs = series(walk)
    assert len(runs) > 3, [len(r) for r in runs]
    # A burst within seconds is still one series.
    same = vector(301)
    burst = [photo(600 + i, i * 0.05, embedding=same) for i in range(5)]
    assert [len(r) for r in series(burst)] == [5]
    # Two minutes apart is no burst.
    apart = [photo(700, 0, embedding=same), photo(701, 3, embedding=same)]
    assert [len(r) for r in series(apart)] == [1, 1]
