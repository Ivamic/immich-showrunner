# SPDX-License-Identifier: AGPL-3.0-or-later
"""Frames out of a video, read over HTTP without fetching the whole file.

The video is opened once; for each point the reader seeks to the key frame at or before it
and decodes that key frame only, so a few frames cost a small part of the file. The turn a
phone wrote into the video is applied, black bars along the edges are cut off, and the frame
is made no larger than needed for a picture. Seeking to the same time gives the same frame,
so a frame chosen once can be fetched again by its time."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import av
import numpy as np
from PIL import Image

LONG_SIDE = 1920
"""Largest side of a frame; a backdrop is 1920 wide."""
FRAMES_PER_VIDEO = 6
OPEN_TIMEOUT = 60.0
BAR_LEVEL = 18
"""Rows and columns this dark at the edges are black bars."""


class FrameError(RuntimeError):
    """The video could not be read."""


@dataclass(frozen=True)
class Grab:
    at: float
    """Seconds from the start: where the reader was asked to look."""
    image: Image.Image


def seconds(duration: str | float | None) -> float:
    """The length of a video as Immich gives it: "H:MM:SS.ffffff" up to 3.3, milliseconds
    from 3.4."""
    if duration is None or duration == "":
        return 0.0
    if isinstance(duration, int | float):
        return float(duration) / 1000
    try:
        hours, minutes, secs = duration.split(":")
        return int(hours) * 3600 + int(minutes) * 60 + float(secs)
    except ValueError:
        return 0.0


def points(duration: float, count: int = FRAMES_PER_VIDEO) -> list[float]:
    """Evenly spread points, away from the very start and end: (i + 0.5) / count."""
    if duration <= 0:
        return [0.0]
    return [round(duration * (i + 0.5) / count, 3) for i in range(count)]


def grab(
    source: str, times: Sequence[float], headers: Mapping[str, str] | None = None
) -> list[Grab]:
    """Frames at the given times from a file or URL. Blocking: run it in a worker thread.

    A time whose frame can not be decoded is left out; a video with no frame at all raises
    FrameError."""
    options = {"headers": "".join(f"{k}: {v}\r\n" for k, v in (headers or {}).items())}
    try:
        container = av.open(source, options=options if headers else {}, timeout=OPEN_TIMEOUT)
    except (av.FFmpegError, OSError) as exc:
        raise FrameError(f"the video could not be opened: {exc}") from exc
    out: list[Grab] = []
    with container:
        if not container.streams.video:
            raise FrameError("there is no picture in the video")
        stream = container.streams.video[0]
        stream.codec_context.skip_frame = "NONKEY"
        for at in times:
            image = _frame_at(container, stream, at)
            if image is not None:
                out.append(Grab(at=at, image=image))
    if not out:
        raise FrameError("no frame could be decoded")
    return out


def _frame_at(
    container: av.container.InputContainer, stream: av.VideoStream, at: float
) -> Image.Image | None:
    try:
        if stream.time_base is not None:
            container.seek(int(at / stream.time_base), stream=stream, backward=True)
        for frame in container.decode(stream):
            image: Image.Image = frame.to_image()  # type: ignore[no-untyped-call]
            if frame.rotation:
                image = image.rotate(frame.rotation, expand=True)
            image = trim_bars(image)
            image.thumbnail((LONG_SIDE, LONG_SIDE), Image.Resampling.LANCZOS)
            return image
    except (av.FFmpegError, OSError, ValueError):
        return None
    return None


def trim_bars(image: Image.Image) -> Image.Image:
    """The picture without black bars along its edges (letterbox and pillarbox)."""
    grey = np.asarray(image.convert("L"), dtype=np.float32)
    rows = np.flatnonzero(grey.mean(axis=1) > BAR_LEVEL)
    cols = np.flatnonzero(grey.mean(axis=0) > BAR_LEVEL)
    if rows.size == 0 or cols.size == 0:
        return image  # all dark: a night or a fade, not bars
    top, bottom, left, right = int(rows[0]), int(rows[-1]) + 1, int(cols[0]), int(cols[-1]) + 1
    height, width = grey.shape
    # Cut only real bars: a few rows at least, and never most of the picture.
    if top < height * 0.02:
        top = 0
    if height - bottom < height * 0.02:
        bottom = height
    if left < width * 0.02:
        left = 0
    if width - right < width * 0.02:
        right = width
    if (bottom - top) < height * 0.5 or (right - left) < width * 0.5:
        return image
    if (top, bottom, left, right) == (0, height, 0, width):
        return image
    return image.crop((left, top, right, bottom))
