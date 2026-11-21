# SPDX-License-Identifier: AGPL-3.0-or-later
"""A process of its own for the slow work of artwork: looking at videos and photos and drawing
pictures.

That work is mostly Python and holds the interpreter: run in a thread of the app, it would make
the page wait. In a separate process the page answers at once while the pictures are made. One
process does it all, one task after another; it is started on the first task and reads the
styles and the face model once."""

from __future__ import annotations

import asyncio
import atexit
import multiprocessing
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any, TypeVar
from uuid import UUID

T = TypeVar("T")


@dataclass(frozen=True)
class HttpSource:
    """Where the videos of Immich are read from; plain data, so it can go to the worker."""

    api_url: str
    """The API of Immich, ending in /api."""
    api_key: str
    original: bool
    """The original files (needs asset.download), or the videos converted for playing."""

    def __call__(self, asset_id: UUID) -> tuple[str, dict[str, str]]:
        path = "original" if self.original else "video/playback"
        return f"{self.api_url}/assets/{asset_id}/{path}", {"x-api-key": self.api_key}


# --- in the worker ------------------------------------------------------------------------


@cache
def _detector() -> Any:
    from showrunner.artwork.faces import FaceDetector

    return FaceDetector()


@cache
def _styles() -> Any:
    from showrunner.artwork.style import builtin_styles

    return builtin_styles()


def look_task(
    asset_id: str, checksum: str, seconds: float, source: HttpSource
) -> list[dict[str, Any]]:
    """The looks of the frames of a video, as kept in the database. Raises FrameError."""
    from showrunner.artwork.make import Video, look_at_video

    video = Video(UUID(asset_id), checksum, seconds)
    return [look.to_dict() for look in look_at_video(video, source, _detector())]


def draw_task(job: dict[str, Any], source: HttpSource) -> bytes:
    """A picture, encoded. Raises ArtworkError."""
    from showrunner.artwork.jobs import ArtworkJob
    from showrunner.artwork.make import draw

    return draw(ArtworkJob.from_dict(job), _styles(), source)


def preview_task(jobs: list[dict[str, Any]], source: HttpSource) -> list[bytes]:
    """Small pictures for a look on the page. Raises ArtworkError."""
    from showrunner.artwork.jobs import ArtworkJob
    from showrunner.artwork.make import draw_small

    return draw_small([ArtworkJob.from_dict(j) for j in jobs], _styles(), source)


@cache
def _embedder(model: str) -> Any:
    from showrunner.slideshow.embed import Embedder

    return Embedder(Path(model))


def photo_look_task(
    asset_id: str, content: bytes, model: str | None
) -> tuple[dict[str, Any], bytes | None]:
    """The look of a photo for slideshows, as kept in the database, and its embedding when the
    model is given. Raises PhotoError."""
    from showrunner.slideshow.embed import pack
    from showrunner.slideshow.photos import look_at_picture, open_photo

    picture, given_side = open_photo(content)
    look = look_at_picture(asset_id, picture, given_side, _detector())
    embedding = pack(_embedder(model).embed(picture)) if model is not None else None
    return look.to_dict(), embedding


def render_task(
    clip: dict[str, Any],
    photos: dict[str, str],
    style_id: str,
    out: str,
    options: dict[str, Any],
    music: dict[str, str] | None = None,
    progress: str | None = None,
) -> dict[str, float]:
    """Draw a slideshow into `out`. Raises RenderError."""
    from showrunner.slideshow.plan import Clip
    from showrunner.slideshow.render import RenderError, RenderOptions, render_clip

    style = _styles().get(style_id)
    if style is None:
        raise RenderError(f"there is no style {style_id!r}")
    done = render_clip(
        Clip.from_dict(clip),
        {key: Path(path) for key, path in photos.items()},
        style,
        Path(out),
        RenderOptions(**options),
        {key: Path(path) for key, path in (music or {}).items()},
        Path(progress) if progress else None,
    )
    return {"frames": done.frames, "seconds": done.seconds, "elapsed": done.elapsed}


def music_task(path: str) -> dict[str, Any]:
    """The analysis of a piece of music, as kept. Raises MusicError."""
    from showrunner.slideshow.music import analyse

    return analyse(Path(path)).to_dict()


# --- in the app ---------------------------------------------------------------------------


class ArtworkWorker:
    def __init__(self) -> None:
        self._pool: ProcessPoolExecutor | None = None

    async def run(self, task: Callable[..., T], *args: Any) -> T:
        if self._pool is None:
            # A fresh interpreter, not a copy of the app with its threads and connections.
            self._pool = ProcessPoolExecutor(
                max_workers=1, mp_context=multiprocessing.get_context("spawn")
            )
        return await asyncio.get_running_loop().run_in_executor(self._pool, task, *args)

    def close(self) -> None:
        if self._pool is not None:
            self._pool.shutdown(wait=False, cancel_futures=True)
            self._pool = None


@cache
def shared_worker() -> ArtworkWorker:
    """The worker of the app, closed when the app ends."""
    worker = ArtworkWorker()
    atexit.register(worker.close)
    return worker


@cache
def render_worker() -> ArtworkWorker:
    """A worker of its own for drawing slideshows: minutes long, it must not hold up the
    pictures and the looks on the page."""
    worker = ArtworkWorker()
    atexit.register(worker.close)
    return worker
