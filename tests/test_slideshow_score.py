# SPDX-License-Identifier: AGPL-3.0-or-later
"""Putting a slideshow to music: changes on the beats, scenes on the first beats of bars, an end
at the end of a phrase, pieces crossing over when one is not long enough, and the same loudness
for every piece."""

import itertools
from datetime import datetime, timedelta

import numpy as np
import pytest

from fake_immich import album_id, asset_id
from showrunner.artwork.quality import Quality
from showrunner.artwork.select import FrameLook
from showrunner.slideshow.music import MusicAnalysis
from showrunner.slideshow.photos import PhotoLook
from showrunner.slideshow.plan import Clip, PlanPhoto, Transition, plan_album
from showrunner.slideshow.score import (
    PEAK_LIMIT,
    TARGET_LUFS,
    Track,
    choose_tracks,
    fit_to_music,
)


def analysis(
    seconds: float = 200.0, bpm: float = 120.0, *, start: float = 0.5, loudness: float = -20.0
) -> MusicAnalysis:
    period = 60 / bpm
    beats = tuple(float(start + i * period) for i in range(int((seconds - start) / period)))
    downbeats = beats[::4]
    return MusicAnalysis(
        seconds=seconds,
        start=start,
        end=beats[-1] + period,
        loudness=loudness,
        true_peak=-3.0,
        tempo=bpm,
        beats=beats,
        downbeats=downbeats,
        meter=4,
        sections=tuple(d for d in downbeats[16::16]),
        energy=(-20.0,) * int(seconds),
        key="C",
        mode="major",
        mood="calm",
    )


def track(n: int, seconds: float = 200.0, **kw: float) -> Track:
    return Track(f"t{n}", analysis(seconds, **kw), f"Piece {n} - Someone - CC BY 4.0", "calm")


def clip(photos: int = 12, scenes: int = 2, *, credits: bool = True) -> Clip:
    items = []
    for n in range(1, photos + 1):
        scene = (n - 1) * scenes // photos
        frame = FrameLook(
            asset_id=str(asset_id(n)),
            at=0.0,
            quality=Quality(0.8, 0.8, 0.8, 0.5, 0.0, 1280, 0.7),
            faces=(),
            point=(0.5, 0.5),
            region=None,
            signature=tuple((n * 37 + i * 11) % 256 for i in range(12 * 12 * 3)),
        )
        look = PhotoLook(frame=frame, width=1280, height=960, given_side=1280, phash=n)
        taken = datetime(2024, 7, 1, 9) + timedelta(minutes=20 * n + 300 * scene)
        items.append(PlanPhoto(asset_id(n), taken, look))
    (made,) = plan_album(album_id(1), "Trip", items, credits=credits)
    return made


def cut_times(made: Clip) -> list[float]:
    """The middle of each transition into a photo or the credits."""
    return [s.start + s.transition_seconds / 2 for s in made.shots[1:]]


def on(times: list[float], grid: np.ndarray) -> bool:
    return all(np.abs(grid - t).min() < 1e-6 for t in times)


def test_photos_change_on_the_beats_and_scenes_on_the_first_beats_of_bars() -> None:
    piece = track(1)
    made = fit_to_music(clip(), [piece])
    beats = np.array(piece.analysis.beats) - piece.analysis.start
    downbeats = np.array(piece.analysis.downbeats) - piece.analysis.start
    assert on(cut_times(made), beats)
    scene_cuts = [
        s.start + s.transition_seconds / 2
        for s in made.shots[1:]
        if s.transition is Transition.FADE_BLACK
    ]
    assert on(scene_cuts, downbeats)
    photos = [s for s in made.shots if s.kind == "photo"]
    for before, after in itertools.pairwise(photos):
        own = (after.start + after.transition_seconds / 2) - (
            before.start + before.transition_seconds / 2
        )
        assert 3.0 - 1e-6 <= own <= 5.0 + 1e-6


def test_the_timeline_stays_whole() -> None:
    made = fit_to_music(clip(), [track(1)])
    assert made.shots[0].start == 0
    for before, after in zip(made.shots, made.shots[1:], strict=False):
        assert after.start == pytest.approx(
            before.start + before.seconds - after.transition_seconds
        )


def test_the_slideshow_ends_on_a_first_beat_of_a_bar_as_the_music_fades() -> None:
    piece = track(1)
    made = fit_to_music(clip(), [piece])
    downbeats = np.array(piece.analysis.downbeats) - piece.analysis.start
    assert on([made.seconds], downbeats)
    credits = made.shots[-1]
    assert credits.kind == "credits"
    assert 3.0 <= credits.seconds - credits.transition_seconds / 2 <= 8.0
    (music,) = made.music
    assert music.at == 0 and music.at + music.seconds == pytest.approx(made.seconds)
    assert music.fade_out == pytest.approx(3.0)
    assert made.music_credits == ("Piece 1 - Someone - CC BY 4.0",)


def test_a_short_piece_gives_way_to_the_next() -> None:
    made = fit_to_music(clip(photos=24, scenes=3), [track(1, 45), track(2, 200)])
    assert [m.track for m in made.music] == ["t1", "t2"]
    first, second = made.music
    assert second.at < first.at + first.seconds, "they cross over"
    assert second.fade_in == pytest.approx(first.at + first.seconds - second.at)
    assert len(made.music_credits) == 2
    assert made.music[-1].at + made.music[-1].seconds == pytest.approx(made.seconds)


def test_every_piece_is_brought_to_the_same_loudness_without_clipping() -> None:
    quiet = Track("q", analysis(loudness=-30.0), "q", "calm")
    loud = Track("l", analysis(loudness=-10.0), "l", "calm")
    assert fit_to_music(clip(), [loud]).music[0].gain_db == pytest.approx(TARGET_LUFS + 10)
    # -30 LUFS would want +14 dB, but its peak at -3 dBTP allows only +2.
    assert fit_to_music(clip(), [quiet]).music[0].gain_db == pytest.approx(PEAK_LIMIT + 3)


def test_without_music_nothing_changes() -> None:
    made = clip()
    assert fit_to_music(made, []) == made


def test_without_credits_the_last_photo_lasts_to_the_end_of_the_phrase() -> None:
    piece = track(1)
    made = fit_to_music(clip(credits=False), [piece])
    assert made.shots[-1].kind == "photo"
    downbeats = np.array(piece.analysis.downbeats) - piece.analysis.start
    assert on([made.seconds], downbeats)


def test_the_choice_of_pieces_is_steady_for_an_album_and_follows_the_mood() -> None:
    pieces = [Track(f"c{i}", analysis(), "", "calm") for i in range(5)] + [
        Track("u1", analysis(), "", "upbeat")
    ]
    first = choose_tracks(pieces, "calm", "album-1/0")
    assert [t.id for t in first] == [t.id for t in choose_tracks(pieces, "calm", "album-1/0")]
    assert all(t.mood == "calm" for t in first)
    assert {t.id for t in first} == {f"c{i}" for i in range(5)}
    assert [t.id for t in choose_tracks(pieces, "calm", "album-2/0")] != [t.id for t in first]
    assert next(t.id for t in choose_tracks(pieces, "solemn", "a")) in {t.id for t in pieces}


def test_the_music_is_kept_with_the_cut_list() -> None:
    made = fit_to_music(clip(), [track(1)])
    again = Clip.from_dict(made.to_dict())
    assert again.to_dict() == made.to_dict()
    assert again.version != clip().version
