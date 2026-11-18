# SPDX-License-Identifier: AGPL-3.0-or-later
"""Looking at videos and drawing pictures: the slow work, done in a worker thread.

Both read the videos from Immich over HTTP; `VideoSource` says where a video is and with which
headers. Nothing here touches the database or the output folders."""

from __future__ import annotations

import io
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from uuid import UUID

from PIL import Image

from showrunner.artwork.faces import FaceDetector
from showrunner.artwork.frames import FrameError, grab, points
from showrunner.artwork.jobs import ArtworkJob
from showrunner.artwork.paint import Frame
from showrunner.artwork.render import encode, render
from showrunner.artwork.select import FrameLook, look
from showrunner.artwork.style import Style

log = logging.getLogger(__name__)

VideoSource = Callable[[UUID], tuple[str, Mapping[str, str]]]
"""The URL of a video and the headers to read it with."""


@dataclass(frozen=True)
class Video:
    asset_id: UUID
    checksum: str
    seconds: float


def look_at_video(video: Video, source: VideoSource, detector: FaceDetector) -> list[FrameLook]:
    """Frames of a video, looked at. Raises FrameError when the video can not be read."""
    url, headers = source(video.asset_id)
    grabs = grab(url, points(video.seconds), headers)
    return [look(str(video.asset_id), g.at, g.image, detector) for g in grabs]


class ArtworkError(RuntimeError):
    """A picture could not be drawn: its frames could not be read again."""


FrameCache = dict[tuple[UUID, float], Image.Image]
"""Frames already read, by video and time: pictures drawn together read each frame once."""


def draw(
    job: ArtworkJob,
    styles: Mapping[str, Style],
    source: VideoSource,
    cache: FrameCache | None = None,
) -> bytes:
    """The picture of a job, encoded. Blocking: run it in a worker thread."""
    style = styles.get(job.style_id)
    if style is None:
        raise ArtworkError(f"there is no style {job.style_id!r}")
    images: FrameCache = {} if cache is None else cache
    frames: list[Frame] = []
    if job.frames:
        missing: dict[UUID, set[float]] = {}
        for chosen in job.frames:
            if (chosen.asset_id, chosen.at) not in images:
                missing.setdefault(chosen.asset_id, set()).add(chosen.at)
        for asset_id, times in missing.items():
            url, headers = source(asset_id)
            try:
                for g in grab(url, sorted(times), headers):
                    images[(asset_id, g.at)] = g.image
            except FrameError as exc:
                raise ArtworkError(f"the frames of {asset_id} could not be read: {exc}") from exc
        for chosen in job.frames:
            image = images.get((chosen.asset_id, chosen.at))
            if image is not None:
                frames.append(Frame(image=image, focus=chosen.point, region=chosen.region))
        if not frames:
            raise ArtworkError("none of the chosen frames could be read")
    rendered = render(style, job.kind, frames, job.text, job.seed)
    return encode(rendered, job.kind)


def draw_small(
    jobs: Sequence[ArtworkJob],
    styles: Mapping[str, Style],
    source: VideoSource,
    long_side: int = 640,
) -> list[bytes]:
    """Several pictures for a look on the page: drawn as usual, then made small (JPEG, or PNG
    for a logo). Blocking: run it in a worker thread."""
    cache: FrameCache = {}
    out: list[bytes] = []
    for job in jobs:
        with Image.open(io.BytesIO(draw(job, styles, source, cache))) as picture:
            picture.load()
            small = picture.copy()
        small.thumbnail((long_side, long_side), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        if small.mode == "RGBA":
            small.save(buffer, "PNG")
        else:
            small.convert("RGB").save(buffer, "JPEG", quality=82)
        out.append(buffer.getvalue())
    return out
