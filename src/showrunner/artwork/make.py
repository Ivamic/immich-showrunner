# SPDX-License-Identifier: AGPL-3.0-or-later
"""Looking at videos and drawing pictures: the slow work, done in a worker thread.

Both read the videos from Immich over HTTP; `VideoSource` says where a video is and with which
headers. Nothing here touches the database or the output folders."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
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


def draw(job: ArtworkJob, styles: Mapping[str, Style], source: VideoSource) -> bytes:
    """The picture of a job, encoded. Blocking: run it in a worker thread."""
    style = styles.get(job.style_id)
    if style is None:
        raise ArtworkError(f"there is no style {job.style_id!r}")
    frames: list[Frame] = []
    if job.frames:
        by_video: dict[UUID, list[float]] = {}
        for chosen in job.frames:
            by_video.setdefault(chosen.asset_id, []).append(chosen.at)
        images: dict[tuple[UUID, float], Image.Image] = {}
        for asset_id, times in by_video.items():
            url, headers = source(asset_id)
            try:
                for g in grab(url, sorted(set(times)), headers):
                    images[(asset_id, g.at)] = g.image
            except FrameError as exc:
                raise ArtworkError(f"the frames of {asset_id} could not be read: {exc}") from exc
        for chosen in job.frames:
            image = images.get((chosen.asset_id, chosen.at))
            if image is None:
                continue
            frames.append(Frame(image=image, focus=chosen.point, region=chosen.region))
        if not frames:
            raise ArtworkError("none of the chosen frames could be read")
    rendered = render(style, job.kind, frames, job.text, job.seed)
    return encode(rendered, job.kind)
