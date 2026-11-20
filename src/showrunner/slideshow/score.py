# SPDX-License-Identifier: AGPL-3.0-or-later
"""Putting a slideshow to music: the photos change on the beats, a new scene on the first beat of a
bar (better still where the music begins a new part), and the slideshow ends where a phrase ends,
with the music fading out under the credits.

The cut list made without music gives each photo the time it should have; here each change is
moved to the beat nearest that time, never giving a photo less than MIN_SECONDS or more than
MAX_SECONDS. A slideshow longer than its piece goes on with the next piece, the two crossing over
at a first beat of a bar. Every piece is brought to the same loudness (-16 LUFS), never above a
true peak of -1 dBTP."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, replace

from showrunner.slideshow.music import MusicAnalysis
from showrunner.slideshow.plan import (
    MAX_SECONDS,
    MIN_SECONDS,
    TITLE_SECONDS,
    AudioPart,
    Clip,
    Shot,
    Transition,
)

TARGET_LUFS = -16.0
PEAK_LIMIT = -1.0
MAX_GAIN = 12.0
FADE_IN = 1.0
FADE_OUT = 3.0
CROSSFADE = 4.0
CREDITS_MIN, CREDITS_MAX = 3.0, 8.0
"""How long the credits may last, so that the music ends at the end of a phrase."""

BEAT, DOWNBEAT, SECTION = 0, 1, 2
PENALTY = {BEAT: 0.35, DOWNBEAT: 0.0, SECTION: -0.2}
"""How much worse than a first beat of a bar a cut is, in seconds of being late or early."""
SCENE_PENALTY = {BEAT: 1.5, DOWNBEAT: 0.0, SECTION: -0.6}


@dataclass(frozen=True)
class Track:
    """A piece of music the slideshows may use."""

    id: str
    analysis: MusicAnalysis
    credit: str
    """One line: the title, who made it, the licence."""
    mood: str


@dataclass(frozen=True)
class _Mark:
    at: float
    strength: int


def choose_tracks(tracks: Sequence[Track], mood: str, key: str) -> list[Track]:
    """The pieces of a mood in the order a slideshow uses them: a different order for each `key`
    (an album and its seed), the same every time for the same key. Without a piece of that mood,
    any piece."""
    fitting = [t for t in tracks if t.mood == mood] or list(tracks)

    def rank(track: Track) -> str:
        return hashlib.sha256(f"{key}/{track.id}".encode()).hexdigest()

    return sorted(fitting, key=rank)


def fit_to_music(clip: Clip, tracks: Sequence[Track]) -> Clip:
    """The clip retimed to the beats of `tracks` (used in turn as long as needed), with its music
    and its credits. Without tracks, the clip as it is."""
    if not tracks:
        return clip
    shots = list(clip.shots)
    photos = [i for i, s in enumerate(shots) if s.kind == "photo"]
    if not photos:
        return clip
    needed = clip.seconds + CREDITS_MAX + FADE_OUT
    parts, marks = _lay_music(tracks, needed)

    # Where each change happens: into the first photo, between photos, into the credits.
    cuts = [_snap(marks, TITLE_SECONDS, TITLE_SECONDS - 1, TITLE_SECONDS + 2, scene=True)]
    for position, index in enumerate(photos):
        shot = shots[index]
        own = shot.seconds - shot.transition_seconds
        following = shots[index + 1] if index + 1 < len(shots) else None
        scene = following is None or following.transition is Transition.FADE_BLACK
        low, high = cuts[-1] + MIN_SECONDS, cuts[-1] + MAX_SECONDS
        if position == len(photos) - 1:
            low = max(low, cuts[-1] + own - 0.5)
        cuts.append(_snap(marks, cuts[-1] + own, low, high, scene=scene))

    last_cut = cuts[-1]
    end = _ending(marks, last_cut, clip.credits)
    retimed = _retime(shots, photos, cuts, end)
    music = _trim(parts, end)
    credits = tuple(dict.fromkeys(t.credit for t in tracks if any(p.track == t.id for p in music)))
    return replace(clip, shots=tuple(retimed), music=tuple(music), music_credits=credits)


def _lay_music(tracks: Sequence[Track], needed: float) -> tuple[list[AudioPart], list[_Mark]]:
    """The pieces one after another, crossing over, until `needed` seconds are covered, and the
    beats of the whole in slideshow time."""
    parts: list[AudioPart] = []
    marks: list[_Mark] = []
    at = 0.0
    index = 0
    while True:
        track = tracks[index % len(tracks)]
        a = track.analysis
        length = a.end - a.start
        offset = at - a.start  # slideshow time of a moment of the piece
        enough = at + length >= needed
        stop = a.end if enough or len(parts) >= 20 else _crossover(a)
        fade_in = FADE_IN if not parts else CROSSFADE
        parts.append(
            AudioPart(
                track=track.id,
                source_start=a.start,
                at=at,
                seconds=stop - a.start + (0.0 if enough else CROSSFADE / 2),
                fade_in=fade_in,
                fade_out=FADE_OUT if enough else CROSSFADE,
                gain_db=_gain(a),
            )
        )
        sections = set(a.sections)
        downbeats = set(a.downbeats)
        first = parts[-1].at + (CROSSFADE / 2 if len(parts) > 1 else 0.0)
        for beat in a.beats:
            when = beat + offset
            if when < first or beat > stop:
                continue
            strength = SECTION if beat in sections else DOWNBEAT if beat in downbeats else BEAT
            marks.append(_Mark(when, strength))
        if enough or len(parts) >= 20:
            return parts, marks
        # The next piece starts so that its sound begins in the middle of the crossover.
        at = stop + offset - CROSSFADE / 2
        index += 1


def _crossover(a: MusicAnalysis) -> float:
    """Where a piece gives way to the next: the start of its last part, or a first beat of a
    bar near its end."""
    late = [s for s in a.sections if s >= a.start + 0.6 * (a.end - a.start)]
    if late:
        return late[-1]
    near_end = [d for d in a.downbeats if d <= a.end - 2.0]
    return near_end[-1] if near_end else a.end - CROSSFADE


def _gain(a: MusicAnalysis) -> float:
    gain = TARGET_LUFS - a.loudness
    return min(gain, MAX_GAIN, PEAK_LIMIT - a.true_peak)


def _snap(marks: Sequence[_Mark], target: float, low: float, high: float, *, scene: bool) -> float:
    """The beat between `low` and `high` best for a change wanted at `target`."""
    penalty = SCENE_PENALTY if scene else PENALTY
    best: tuple[float, float] | None = None
    for mark in marks:
        if mark.at < low or mark.at > high:
            continue
        cost = abs(mark.at - target) + penalty[mark.strength]
        if best is None or cost < best[0]:
            best = (cost, mark.at)
    if best is None:
        return min(max(target, low), high)
    return best[1]


def _ending(marks: Sequence[_Mark], last_cut: float, credits: bool) -> float:
    """Where the slideshow and its music end: the end of a phrase after the credits (or after
    the last photo), the music fading out over FADE_OUT before it."""
    low, high = last_cut + CREDITS_MIN + 1.0, last_cut + CREDITS_MAX
    if not credits:
        low, high = last_cut + 1.0, last_cut + 4.0
    downbeats = [m for m in marks if m.strength >= DOWNBEAT and low <= m.at <= high]
    if not downbeats:
        return low + (high - low) / 2
    # The end of a phrase: prefer a new part, then the earliest first beat of a bar.
    sections = [m for m in downbeats if m.strength == SECTION]
    return (sections or downbeats)[0].at


def _retime(shots: list[Shot], photos: list[int], cuts: list[float], end: float) -> list[Shot]:
    """The shots placed between the cuts: each transition is centred on its cut."""
    result: list[Shot] = []
    for i, shot in enumerate(shots):
        if shot.kind == "title":
            following = shots[photos[0]]
            stop = cuts[0] + following.transition_seconds / 2
            result.append(replace(shot, start=0.0, seconds=stop))
            continue
        if shot.kind == "photo":
            position = photos.index(i)
            begin = cuts[position] - shot.transition_seconds / 2
            following_shot = shots[i + 1] if i + 1 < len(shots) else None
            if following_shot is None:
                stop = end
            else:
                stop = cuts[position + 1] + following_shot.transition_seconds / 2
            result.append(replace(shot, start=begin, seconds=stop - begin))
            continue
        # The credits.
        begin = cuts[-1] - shot.transition_seconds / 2
        result.append(replace(shot, start=begin, seconds=end - begin))
    return result


def _trim(parts: list[AudioPart], end: float) -> list[AudioPart]:
    """The music up to the end of the slideshow, fading out before it."""
    kept: list[AudioPart] = []
    for part in parts:
        if part.at >= end:
            break
        if part.at + part.seconds >= end:
            part = replace(part, seconds=end - part.at, fade_out=FADE_OUT)
        kept.append(part)
    return kept


__all__ = ["Track", "choose_tracks", "fit_to_music"]
