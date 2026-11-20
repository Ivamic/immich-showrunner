# SPDX-License-Identifier: AGPL-3.0-or-later
"""Drawing a slideshow: a small one from synthetic photos, read back frame by frame — its
length, the title first, each photo in its place, black in the middle of a fade, a standing
photo over its blurred copy, and nothing left behind when a photo is missing."""

from datetime import datetime, timedelta
from pathlib import Path

import av
import numpy as np
import pytest
from PIL import Image

from fake_immich import album_id, asset_id
from showrunner.artwork.quality import Quality
from showrunner.artwork.select import FrameLook
from showrunner.artwork.style import builtin_styles
from showrunner.slideshow.photos import PhotoLook
from showrunner.slideshow.plan import Clip, Layout, PlanPhoto, Transition, plan_album
from showrunner.slideshow.render import RenderError, RenderOptions, render_clip

OPTIONS = RenderOptions(width=320, height=180, fps=10, preset="ultrafast", threads=1)
STYLE = builtin_styles()["editorial"]
COLORS = [
    (200, 40, 40),
    (40, 160, 60),
    (40, 60, 200),
    (220, 200, 40),
    (160, 40, 160),
    (40, 180, 180),
]


def picture(color: tuple[int, int, int], size: tuple[int, int]) -> Image.Image:
    """A photo of one colour with a soft gradient, so that the camera has something to move."""
    w, h = size
    x = np.linspace(0.85, 1.0, w, dtype=np.float32)[np.newaxis, :, np.newaxis]
    rgb = np.ones((h, w, 3), np.float32) * np.array(color, np.float32) * x
    return Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8))


def plan_photo(n: int, size: tuple[int, int]) -> PlanPhoto:
    frame = FrameLook(
        asset_id=str(asset_id(n)),
        at=0.0,
        quality=Quality(0.8, 0.8, 0.8, 0.5, 0.0, max(size), 0.7),
        faces=(),
        point=(0.5, 0.5),
        region=None,
        signature=tuple((n * 37 + i * 11) % 256 for i in range(12 * 12 * 3)),
    )
    look = PhotoLook(frame=frame, width=size[0], height=size[1], given_side=max(size), phash=n)
    # Two scenes: the last three photos three hours after the first three.
    minutes = 20 * n + (180 if n > 3 else 0)
    return PlanPhoto(asset_id(n), datetime(2024, 7, 1, 9) + timedelta(minutes=minutes), look)


@pytest.fixture
def album(tmp_path: Path) -> tuple[Clip, dict[str, Path]]:
    files: dict[str, Path] = {}
    photos = []
    for n, color in enumerate(COLORS, start=1):
        size = (600, 800) if n == 4 else (800, 600)  # the fourth stands
        path = tmp_path / f"p{n}.jpg"
        picture(color, size).save(path, quality=92)
        files[str(asset_id(n))] = path
        photos.append(plan_photo(n, size))
    (clip,) = plan_album(album_id(1), "Trip", photos)
    return clip, files


def frames_of(path: Path) -> list[np.ndarray]:
    with av.open(str(path)) as file:
        return [f.to_ndarray(format="rgb24") for f in file.decode(video=0)]


def at(frames: list[np.ndarray], t: float) -> np.ndarray:
    return frames[min(len(frames) - 1, round(t * OPTIONS.fps))]


def test_a_slideshow_is_drawn_frame_by_frame(
    album: tuple[Clip, dict[str, Path]], tmp_path: Path
) -> None:
    clip, files = album
    out = tmp_path / "show.mp4"
    done = render_clip(clip, files, STYLE, out, OPTIONS)
    assert out.exists() and not list(tmp_path.glob(".*.part"))
    frames = frames_of(out)
    assert len(frames) == done.frames == round(clip.seconds * OPTIONS.fps)
    assert frames[0].shape == (180, 320, 3)

    title = at(frames, 1.0)
    assert title.mean() > 60, "the title of the style, not black"

    photo_shots = [s for s in clip.shots if s.kind == "photo"]
    for shot, color in zip(photo_shots, COLORS, strict=True):
        middle = at(frames, shot.start + shot.transition_seconds + 1.0)
        if shot.layout is Layout.BLURRED:
            middle = middle[:, 120:200]  # the photo itself, in the middle
        got = middle.reshape(-1, 3).mean(axis=0)
        assert np.abs(got - np.array(color) * 0.92).max() < 30, (shot.asset_id, got, color)

    fade = next(s for s in photo_shots if s.transition is Transition.FADE_BLACK and s.scene > 1)
    black = at(frames, fade.start + fade.transition_seconds / 2)
    assert black.mean() < 12, "the middle of a fade is black"


def test_a_standing_photo_is_shown_over_its_blurred_copy(
    album: tuple[Clip, dict[str, Path]], tmp_path: Path
) -> None:
    clip, files = album
    out = tmp_path / "show.mp4"
    render_clip(clip, files, STYLE, out, OPTIONS)
    frames = frames_of(out)
    standing = next(s for s in clip.shots if s.layout is Layout.BLURRED)
    frame = at(frames, standing.start + standing.transition_seconds + 1.0).astype(np.float32)
    sides = np.concatenate([frame[:, :30], frame[:, -30:]], axis=1).reshape(-1, 3).mean(axis=0)
    middle = frame[:, 130:190].reshape(-1, 3).mean(axis=0)
    yellow = np.array(COLORS[3], np.float32)
    assert sides.mean() > 25, "the sides are not black: the blurred copy"
    assert (sides < middle).all(), "darker than the photo itself"
    assert np.abs(middle - yellow * 0.92).max() < 30


def test_a_missing_photo_leaves_nothing_behind(
    album: tuple[Clip, dict[str, Path]], tmp_path: Path
) -> None:
    clip, files = album
    del files[str(asset_id(2))]
    out = tmp_path / "show.mp4"
    with pytest.raises(RenderError):
        render_clip(clip, files, STYLE, out, OPTIONS)
    assert not out.exists() and not list(tmp_path.glob(".*.part"))


def test_a_slideshow_gets_its_music(album: tuple[Clip, dict[str, Path]], tmp_path: Path) -> None:
    from test_slideshow_music import piece, write

    from showrunner.slideshow.music import analyse, measure_loudness
    from showrunner.slideshow.score import Track, fit_to_music

    clip, files = album
    song = write(tmp_path / "song.wav", piece(seconds=60, bpm=120))
    track = Track("song", analyse(song), "Song - Someone - CC0", "calm")
    scored = fit_to_music(clip, [track])
    out = tmp_path / "show.mp4"
    render_clip(scored, files, STYLE, out, OPTIONS, {"song": song})
    with av.open(str(out)) as file:
        assert len(file.streams.audio) == 1
        audio = file.streams.audio[0]
        samples = np.concatenate([f.to_ndarray() for f in file.decode(audio)], axis=1)
        heard = samples.shape[1] / audio.rate
    assert heard == pytest.approx(scored.seconds, abs=0.1)
    assert np.abs(samples[:, : audio.rate // 20]).max() < 0.05, "it fades in"
    sound = write(tmp_path / "heard.wav", np.ascontiguousarray(samples), codec="pcm_f32le")
    loudness, peak = measure_loudness(sound)
    # Brought towards -16 LUFS as far as the peaks of the piece allow.
    (part,) = scored.music
    assert loudness == pytest.approx(track.analysis.loudness + part.gain_db, abs=1.0)
    assert peak <= -0.5


def test_missing_music_leaves_nothing_behind(
    album: tuple[Clip, dict[str, Path]], tmp_path: Path
) -> None:
    from showrunner.slideshow.plan import AudioPart

    clip, files = album
    scored = Clip.from_dict(
        {**clip.to_dict(), "music": [AudioPart("gone", 0, 0, 5, 1, 1, 0).to_dict()]}
    )
    out = tmp_path / "show.mp4"
    with pytest.raises(RenderError, match="music"):
        render_clip(scored, files, STYLE, out, OPTIONS, {})
    assert not out.exists()


def test_the_credits_are_drawn_readably_in_every_style() -> None:
    from PIL import Image as PilImage

    from showrunner.slideshow.render import _contrast, _credits, _luminance, _readable

    lines = ["\u201cPiece\u201d by Someone, CC BY 4.0, trimmed and faded"]
    for style in builtin_styles().values():
        image = _credits(style, lines)
        assert image.size == (1920, 1080), style.id
    dark = PilImage.new("RGB", (100, 100), (60, 40, 30))
    assert _readable((70, 50, 40, 255), dark, 0, 100) == (255, 255, 255, 255)
    light = PilImage.new("RGB", (100, 100), (240, 235, 225))
    assert _readable((107, 74, 47, 255), light, 0, 100) == (107, 74, 47, 255), "the style's own"
    assert _contrast(_luminance((255, 255, 255)), _luminance((0, 0, 0))) == pytest.approx(21)
