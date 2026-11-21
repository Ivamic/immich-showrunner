# SPDX-License-Identifier: AGPL-3.0-or-later
"""Drawing a slideshow from its cut list: frames from the photos, the camera moving smoothly
(OpenCV, sub-pixel), dissolves and fades through black, the title and the credits in the style
of the album, all encoded to H.264 with PyAV (D-090, D-098). No ffmpeg program is run.

Blocking and slow (a minute or two for a few minutes of video): it runs in a worker process of
its own. The frames are built while the previous ones are encoded, in another thread: both
OpenCV and the encoder let go of the interpreter while they work."""

from __future__ import annotations

import contextlib
import json
import logging
import math
import os
import queue
import threading
import time
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import av
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from showrunner.artwork.paint import Frame, rgba
from showrunner.artwork.render import render
from showrunner.artwork.style import OutputKind, Style, text_block
from showrunner.artwork.text import font
from showrunner.slideshow.photos import open_photo
from showrunner.slideshow.plan import Clip, Layout, Rect, Shot, Transition

log = logging.getLogger(__name__)

CREDIT_LINE = "Made with Showrunner for Immich"
"""Always in English (D-098)."""
MAX_SIDE = 6000
"""Photos are never decoded larger than this, whatever the camera needs."""
BLUR_SIDE = 480
"""The blurred background is made from a copy this small: as good, and quick."""
BACKGROUND_DIM = 0.55
QUEUE_FRAMES = 8
PROGRESS_EVERY = 30
"""Frames between two notes of how far the drawing is (for the page)."""


class RenderError(RuntimeError):
    """A slideshow could not be drawn: a photo is missing or can not be read."""


@dataclass(frozen=True)
class RenderOptions:
    width: int = 1920
    height: int = 1080
    fps: int = 30
    crf: int = 20
    preset: str = "veryfast"
    threads: int = 2


@dataclass(frozen=True)
class Rendered:
    frames: int
    seconds: float
    elapsed: float


def render_clip(
    clip: Clip,
    photos: Mapping[str, Path],
    style: Style,
    out: Path,
    options: RenderOptions = RenderOptions(),
    music: Mapping[str, Path] | None = None,
    progress: Path | None = None,
) -> Rendered:
    """Draw `clip` into the MP4 file `out` (written under another name and renamed when it is
    done). `photos` gives the file of each photo of the clip by asset id, `music` the file of
    each piece of its music by id. Raises RenderError."""
    started = time.monotonic()
    cv2.setNumThreads(max(1, options.threads))
    pictures = _Pictures(clip, photos, options)
    stills = _stills(clip, style, photos, options)
    total = max(1, round(clip.seconds * options.fps))
    sound = _mix(clip, music or {}, total / options.fps) if clip.music else None
    partial = out.with_name(f".{out.name}.part")
    frames: queue.Queue[np.ndarray | None] = queue.Queue(maxsize=QUEUE_FRAMES)
    failure: list[BaseException] = []

    def build() -> None:
        try:
            for index in range(total):
                frames.put(_frame(clip, index / options.fps, pictures, stills, options))
        except BaseException as exc:
            failure.append(exc)
        finally:
            frames.put(None)

    builder = threading.Thread(target=build, name="slideshow-frames", daemon=True)
    builder.start()
    written = 0
    try:
        with av.open(str(partial), "w", format="mp4", options={"movflags": "+faststart"}) as file:
            stream = file.add_stream("libx264", rate=options.fps)
            stream.width, stream.height = options.width, options.height
            stream.pix_fmt = "yuv420p"
            stream.options = {
                "preset": options.preset,
                "crf": str(options.crf),
                "threads": str(max(1, options.threads)),
            }
            audio = _AudioOut(file, sound) if sound is not None else None
            while (frame := frames.get()) is not None:
                video = av.VideoFrame.from_ndarray(frame, format="bgr24")
                for packet in stream.encode(video):
                    file.mux(packet)
                written += 1
                if audio is not None:
                    # Sound up to the time of this frame, so that the two are interleaved.
                    audio.write_until(written / options.fps)
                if progress is not None and written % PROGRESS_EVERY == 0:
                    _progress(progress, written, total)
            for packet in stream.encode():
                file.mux(packet)
            if audio is not None:
                audio.finish()
        builder.join()
        if failure:
            raise RenderError(f"the frames could not be made: {failure[0]}") from failure[0]
        os.replace(partial, out)
    finally:
        # Let a builder that waits on a full queue finish, then leave no partial file behind.
        while builder.is_alive():
            with contextlib.suppress(queue.Empty):
                frames.get(timeout=0.1)
        partial.unlink(missing_ok=True)
    return Rendered(
        frames=written, seconds=written / options.fps, elapsed=time.monotonic() - started
    )


def _progress(path: Path, done: int, total: int) -> None:
    """How far the drawing is, for the page: written whole, never half."""
    partial = path.with_name(f".{path.name}.part")
    try:
        partial.write_text(json.dumps({"frames": done, "total": total}), encoding="utf-8")
        os.replace(partial, path)
    except OSError:
        pass  # only a note for the page


# --- the sound ------------------------------------------------------------------------------


AUDIO_RATE = 48000
AUDIO_BITRATE = 192_000
PEAK = 10 ** (-1 / 20)
"""The mix never goes above -1 dBFS."""


def _mix(clip: Clip, music: Mapping[str, Path], seconds: float) -> np.ndarray:
    """The music of the clip as one stereo track at AUDIO_RATE, `seconds` long: each part at
    its place, brought to its gain, faded in and out."""
    from showrunner.slideshow.music import MusicError, decode

    length = round(seconds * AUDIO_RATE)
    mix = np.zeros((2, length), np.float32)
    decoded: dict[str, np.ndarray] = {}
    for part in clip.music:
        path = music.get(part.track)
        if path is None:
            raise RenderError(f"the music {part.track} is missing")
        if part.track not in decoded:
            try:
                decoded[part.track] = decode(path, AUDIO_RATE, "stereo")
            except MusicError as exc:
                raise RenderError(f"the music {part.track} could not be read: {exc}") from exc
        source = decoded[part.track]
        first = round(part.source_start * AUDIO_RATE)
        at = round(part.at * AUDIO_RATE)
        count = min(round(part.seconds * AUDIO_RATE), source.shape[1] - first, length - at)
        if count <= 0:
            continue
        piece = source[:, first : first + count] * np.float32(10 ** (part.gain_db / 20))
        piece *= _envelope(count, part.fade_in, part.fade_out)
        mix[:, at : at + count] += piece
    peak = float(np.abs(mix).max(initial=0.0))
    if peak > PEAK:
        mix *= np.float32(PEAK / peak)
    return mix


def _envelope(count: int, fade_in: float, fade_out: float) -> np.ndarray:
    """Gain over a part: rising over `fade_in`, falling over `fade_out` (quarter sine waves, so
    that two pieces crossing over keep their joint loudness)."""
    gain = np.ones(count, np.float32)
    rise = min(count, round(fade_in * AUDIO_RATE))
    if rise > 0:
        gain[:rise] = np.sin(np.linspace(0, np.pi / 2, rise, dtype=np.float32))
    fall = min(count, round(fade_out * AUDIO_RATE))
    if fall > 0:
        gain[count - fall :] *= np.cos(np.linspace(0, np.pi / 2, fall, dtype=np.float32))
    return gain


class _AudioOut:
    """AAC sound written alongside the frames."""

    FRAME = 1024

    def __init__(self, file: Any, sound: np.ndarray) -> None:
        self._file = file
        self._sound = sound
        self._stream = file.add_stream("aac", rate=AUDIO_RATE)
        self._stream.layout = "stereo"
        self._stream.bit_rate = AUDIO_BITRATE
        self._done = 0

    def write_until(self, seconds: float) -> None:
        stop = min(self._sound.shape[1], round(seconds * AUDIO_RATE))
        while self._done + self.FRAME <= stop:
            self._write(self._done + self.FRAME)

    def finish(self) -> None:
        while self._done < self._sound.shape[1]:
            self._write(min(self._sound.shape[1], self._done + self.FRAME))
        for packet in self._stream.encode():
            self._file.mux(packet)

    def _write(self, stop: int) -> None:
        chunk = np.ascontiguousarray(self._sound[:, self._done : stop])
        frame = av.AudioFrame.from_ndarray(chunk, format="fltp", layout="stereo")
        frame.sample_rate = AUDIO_RATE
        frame.pts = self._done
        for packet in self._stream.encode(frame):
            self._file.mux(packet)
        self._done = stop


# --- the pictures ---------------------------------------------------------------------------


@dataclass
class _Picture:
    image: np.ndarray
    """BGR, at the size the camera needs."""
    background: np.ndarray | None = None
    """For a standing photo: the blurred copy behind it, at the size of the video."""


class _Pictures:
    """The photos of a clip, decoded when the camera first needs them; only the last few are
    kept, as a shot needs its photo and at most the one before (a long clip would otherwise hold
    gigabytes)."""

    KEEP = 3

    def __init__(self, clip: Clip, photos: Mapping[str, Path], options: RenderOptions) -> None:
        self._shots = {str(s.asset_id): s for s in clip.shots if s.asset_id and s.move}
        missing = [key for key in self._shots if key not in photos]
        if missing:
            raise RenderError(f"the photo {missing[0]} is missing")
        self._photos = photos
        self._options = options
        self._kept: OrderedDict[str, _Picture] = OrderedDict()

    def __getitem__(self, key: str) -> _Picture:
        picture = self._kept.get(key)
        if picture is None:
            picture = self._load(key)
            self._kept[key] = picture
            while len(self._kept) > self.KEEP:
                self._kept.popitem(last=False)
        else:
            self._kept.move_to_end(key)
        return picture

    def _load(self, key: str) -> _Picture:
        shot = self._shots[key]
        try:
            content = self._photos[key].read_bytes()
            # Opened once small to learn its shape, then at the size the camera needs.
            probe, _ = open_photo(content, 256)
            aspect = probe.width / max(1, probe.height)
            picture, _ = open_photo(content, _needed_side(shot, aspect, self._options))
        except (OSError, ValueError) as exc:
            raise RenderError(f"the photo {key} could not be read: {exc}") from exc
        bgr = cv2.cvtColor(np.asarray(picture), cv2.COLOR_RGB2BGR)
        background = _blurred(bgr, self._options) if shot.layout is Layout.BLURRED else None
        return _Picture(bgr, background)


def _needed_side(shot: Shot, aspect: float, options: RenderOptions) -> int:
    """The long side the photo is decoded at: enough pixels for the closest frame."""
    assert shot.move is not None
    width = min(rect[2] for rect in shot.move)
    height = min(rect[3] for rect in shot.move)
    if shot.layout is Layout.BLURRED:
        # Shown whole, as high as the video: only its height matters.
        photo_height = options.height / height
        photo_width = photo_height * aspect
    else:
        photo_width = max(options.width / width, options.height / height * aspect)
        photo_height = photo_width / aspect
    return min(MAX_SIDE, math.ceil(max(photo_width, photo_height)))


def _blurred(bgr: np.ndarray, options: RenderOptions) -> np.ndarray:
    """The photo enlarged to cover the video, blurred and darkened."""
    h, w = bgr.shape[:2]
    scale = min(1.0, BLUR_SIDE / max(h, w))
    small = cv2.resize(bgr, (max(1, round(w * scale)), max(1, round(h * scale))))
    sh, sw = small.shape[:2]
    target = options.width / options.height
    if sw / sh < target:  # crop height
        ch = max(1, round(sw / target))
        top = (sh - ch) // 2
        small = small[top : top + ch]
    else:
        cw = max(1, round(sh * target))
        left = (sw - cw) // 2
        small = small[:, left : left + cw]
    blurred = cv2.GaussianBlur(small, (0, 0), sigmaX=max(2.0, small.shape[1] / 40))
    large = cv2.resize(blurred, (options.width, options.height), interpolation=cv2.INTER_LINEAR)
    return (large.astype(np.float32) * BACKGROUND_DIM).astype(np.uint8)


def _stills(
    clip: Clip, style: Style, photos: Mapping[str, Path], options: RenderOptions
) -> dict[str, np.ndarray]:
    """The title (the landscape picture of the style, from the photos of the clip) and the
    credits, at the size of the video."""
    frames = []
    shown = [s for s in clip.shots if s.asset_id is not None]
    for shot in shown[: style.spec.max_frames]:
        key = str(shot.asset_id)
        try:
            image, _ = open_photo(photos[key].read_bytes())
        except (KeyError, OSError, ValueError) as exc:
            raise RenderError(f"the photo {key} could not be read: {exc}") from exc
        frames.append(Frame(image=image))
    stills = {"title": _still(render(style, OutputKind.LANDSCAPE, frames, clip.caption, 0).image)}
    if clip.credits:
        stills["credits"] = _still(_credits(style, clip.music_credits))
    return {k: _sized(v, options) for k, v in stills.items()}


def _credits(style: Style, music: Sequence[str]) -> Image.Image:
    """The credits: the background of the style's landscape picture, the music (a line a
    piece) and, below it, the line of the app, in the font and colour of the style's title."""
    canvas = render(style, OutputKind.LANDSCAPE, [], "", 0).image.convert("RGBA")
    output, owner = style.output(OutputKind.LANDSCAPE)
    spec = text_block(output, None)
    color = rgba(spec.color) if spec is not None else (255, 255, 255, 255)
    face = owner.font_path(spec.font) if spec is not None else None
    width, height = canvas.size
    lines: list[tuple[str, int]] = [(f"Music: {line}", round(height * 0.032)) for line in music]
    lines.append((CREDIT_LINE, round(height * 0.042)))
    draw = ImageDraw.Draw(canvas)
    fonts = []
    for text, size in lines:
        font_size = size
        while True:
            loaded = (
                font(face.path, font_size, face.index, face.variation)
                if face is not None
                else ImageFont.load_default(size=font_size)
            )
            if draw.textlength(text, font=loaded) <= width * 0.86 or font_size <= 12:
                break
            font_size -= 2
        fonts.append(loaded)
    gap = round(height * 0.02)
    heights = [f.getbbox("Ag")[3] for f in fonts]
    total = sum(heights) + gap * (len(lines) - 1) + (gap * 2 if music else 0)
    y = _quiet_band(canvas, total)
    color = _readable(color, canvas, y, total)
    for index, ((text, _), loaded, line_height) in enumerate(
        zip(lines, fonts, heights, strict=True)
    ):
        if music and index == len(lines) - 1:
            y += gap * 2  # the line of the app apart from the music
        x = (width - draw.textlength(text, font=loaded)) / 2
        draw.text((x, y), text, font=loaded, fill=color)
        y += line_height + gap
    return canvas


def _quiet_band(canvas: Image.Image, band: float) -> float:
    """The top of the calmest stretch of the background `band` pixels high, near the middle:
    not over the holes of a film strip or the pins of a board."""
    grey = np.asarray(canvas.convert("L").resize((64, 90)), dtype=np.float32)
    rows = grey.shape[0]
    size = max(1, round(band / canvas.height * rows))
    best: tuple[float, int] = (np.inf, (rows - size) // 2)
    for top in range(round(rows * 0.08), round(rows * 0.92) - size + 1):
        stretch = grey[max(0, top - 1) : top + size + 1]
        middle = abs((top + size / 2) / rows - 0.5)
        cost = float(stretch.std()) + 40 * middle
        if cost < best[0]:
            best = (cost, top)
    return float(best[1] / rows * canvas.height)


def _readable(
    color: tuple[int, int, int, int], canvas: Image.Image, y: float, band: float
) -> tuple[int, int, int, int]:
    """The colour of the style when it stands out from the background under the text (WCAG
    contrast of 3 or more), white or black otherwise."""
    strip = canvas.convert("RGB").crop((0, round(y), canvas.width, round(y + band)))
    behind = _luminance(tuple(np.asarray(strip, dtype=np.float32).reshape(-1, 3).mean(axis=0)))
    if _contrast(_luminance(color[:3]), behind) >= 3:
        return color
    return (255, 255, 255, 255) if behind < 0.4 else (20, 20, 20, 255)


def _luminance(rgb: Sequence[float]) -> float:
    def channel(value: float) -> float:
        v = value / 255
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(float(v)) for v in rgb[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a: float, b: float) -> float:
    light, dark = max(a, b), min(a, b)
    return (light + 0.05) / (dark + 0.05)


def _still(image: Image.Image) -> np.ndarray:
    if image.mode == "RGBA":
        black = Image.new("RGBA", image.size, (0, 0, 0, 255))
        image = Image.alpha_composite(black, image)
    return cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2BGR)


def _sized(bgr: np.ndarray, options: RenderOptions) -> np.ndarray:
    if bgr.shape[1] == options.width and bgr.shape[0] == options.height:
        return bgr
    return cv2.resize(bgr, (options.width, options.height), interpolation=cv2.INTER_AREA)


# --- the frames -----------------------------------------------------------------------------


def _frame(
    clip: Clip,
    t: float,
    pictures: _Pictures,
    stills: Mapping[str, np.ndarray],
    options: RenderOptions,
) -> np.ndarray:
    """The frame at time `t`: the shot on screen, mixed with the next one during its
    transition."""
    active = [s for s in clip.shots if s.start <= t < s.start + s.seconds]
    if not active:
        return np.zeros((options.height, options.width, 3), np.uint8)
    current = active[-1]
    image = _shot_frame(current, t, pictures, stills, options)
    if len(active) == 1 or current.transition_seconds <= 0:
        return image
    previous = _shot_frame(active[-2], t, pictures, stills, options)
    share = min(1.0, max(0.0, (t - current.start) / current.transition_seconds))
    if current.transition is Transition.FADE_BLACK:
        if share < 0.5:
            return _dim(previous, 1 - 2 * share)
        return _dim(image, 2 * share - 1)
    if current.transition is Transition.DISSOLVE:
        return cv2.addWeighted(previous, 1 - share, image, share, 0)
    return image


def _dim(image: np.ndarray, share: float) -> np.ndarray:
    return cv2.convertScaleAbs(image, alpha=max(0.0, min(1.0, share)))


def _shot_frame(
    shot: Shot,
    t: float,
    pictures: _Pictures,
    stills: Mapping[str, np.ndarray],
    options: RenderOptions,
) -> np.ndarray:
    if shot.asset_id is None or shot.move is None:
        still = stills.get(shot.kind)
        if still is None:
            return np.zeros((options.height, options.width, 3), np.uint8)
        return still
    picture = pictures[str(shot.asset_id)]
    share = min(1.0, max(0.0, (t - shot.start) / max(shot.seconds, 1e-6)))
    rect = _between(shot.move[0], shot.move[1], _ease(share))
    if shot.layout is Layout.BLURRED and picture.background is not None:
        return _over_blurred(picture, rect, options)
    return _crop(picture.image, rect, options.width, options.height)


def _ease(share: float) -> float:
    """Slow at both ends: the camera starts and stops gently."""
    return share * share * (3 - 2 * share)


def _between(a: Rect, b: Rect, share: float) -> Rect:
    return (
        a[0] + (b[0] - a[0]) * share,
        a[1] + (b[1] - a[1]) * share,
        a[2] + (b[2] - a[2]) * share,
        a[3] + (b[3] - a[3]) * share,
    )


def _crop(image: np.ndarray, rect: Rect, width: int, height: int) -> np.ndarray:
    """The part `rect` of the image, brought to width x height, sub-pixel exact."""
    h, w = image.shape[:2]
    x, y, rw, rh = rect[0] * w, rect[1] * h, rect[2] * w, rect[3] * h
    sx, sy = width / rw, height / rh
    matrix = np.array([[sx, 0, -x * sx], [0, sy, -y * sy]], np.float32)
    flags = cv2.INTER_AREA if sx < 0.5 else cv2.INTER_LINEAR
    return cv2.warpAffine(
        image, matrix, (width, height), flags=flags, borderMode=cv2.BORDER_REPLICATE
    )


def _over_blurred(picture: _Picture, rect: Rect, options: RenderOptions) -> np.ndarray:
    """A standing photo: the part `rect` of it, as high as the video, in the middle of its
    blurred copy."""
    assert picture.background is not None
    h, w = picture.image.shape[:2]
    x, y, rw, rh = rect[0] * w, rect[1] * h, rect[2] * w, rect[3] * h
    scale = options.height / rh
    shown = rw * scale
    left = (options.width - shown) / 2
    matrix = np.array([[scale, 0, left - x * scale], [0, scale, -y * scale]], np.float32)
    canvas = picture.background.copy()
    cv2.warpAffine(
        picture.image,
        matrix,
        (options.width, options.height),
        dst=canvas,
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_TRANSPARENT,
    )
    return canvas
