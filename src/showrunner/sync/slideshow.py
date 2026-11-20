# SPDX-License-Identifier: AGPL-3.0-or-later
"""The slideshow step of a pass: look at the photos of the albums not looked at yet.

A photo is downloaded from Immich and looked at in the worker process (about a second for a
large one), so a large library is looked at over several passes, as videos are for artwork: each
pass stops after its time budget, and an album with photos still to look at is not stamped, so
that the next quick pass comes back to it.

Photos are looked at in full size when the key may download them; otherwise, and for HEIC or RAW
when Immich makes no full-size pictures, the preview of Immich is what there is."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from uuid import UUID

from showrunner.artwork.worker import ArtworkWorker, photo_look_task, shared_worker
from showrunner.immich.client import ImmichClient, ImmichError, ImmichUnreachableError
from showrunner.immich.models import Album, Asset
from showrunner.slideshow.photos import PhotoError, PhotoLook, look_version
from showrunner.store.registry import Registry

log = logging.getLogger(__name__)

PREVIEW_SHARE = 0.9
"""A picture with a long side below this share of the photo's is a preview, not the photo."""


@dataclass
class SlideshowContext:
    """What the slideshow step needs. The slow work runs in the worker process."""

    full: bool
    """The key may download: photos are looked at in full size."""
    budget_seconds: float = 240.0
    worker: ArtworkWorker = field(default_factory=shared_worker)
    clock: Callable[[], float] = time.monotonic

    async def look(self, asset_id: UUID, content: bytes) -> PhotoLook:
        """Raises PhotoError."""
        data = await self.worker.run(photo_look_task, str(asset_id), content)
        found = PhotoLook.from_dict(data)
        if found is None:  # pragma: no cover - the worker runs the same code
            raise PhotoError("the worker made a look of another version")
        return found


@dataclass
class PhotoReport:
    looked: int = 0
    unreadable: int = 0
    # Photos that came smaller than they are: previews instead of the photos.
    previews: int = 0
    # Albums with photos still to look at, and how many.
    waiting: dict[UUID, int] = field(default_factory=dict)

    @property
    def incomplete(self) -> set[UUID]:
        return set(self.waiting)


async def look_at_photos(
    immich: ImmichClient,
    albums: Sequence[Album],
    registry: Registry,
    context: SlideshowContext,
) -> PhotoReport:
    """Look at the photos of `albums` that have no look of this version for their checksum.
    Raises ImmichError when an album can not be listed (the pass stops, as for videos)."""
    report = PhotoReport()
    photos: dict[UUID, list[Asset]] = {}
    for album in albums:
        photos[album.id] = [photo async for photo in immich.album_photos(album.id)]
    ids = {photo.id for every in photos.values() for photo in every}
    rows = await registry.photo_looks(ids)
    version = look_version()
    started = context.clock()
    done: set[UUID] = set()
    stopped = False
    for album in albums:
        for photo in photos[album.id]:
            row = rows.get(photo.id)
            checksum = photo.checksum or ""
            if photo.id in done or (
                row is not None and row.checksum == checksum and row.version == version
            ):
                continue
            if stopped or context.clock() - started >= context.budget_seconds:
                stopped = True
                report.waiting[album.id] = report.waiting.get(album.id, 0) + 1
                continue
            try:
                look = await _look(immich, context, photo)
            except ImmichError as exc:
                if not _transient(exc):
                    log.warning("photo %s could not be read for slideshows: %s", photo.id, exc)
                    look = None
                else:
                    # Not the photo's fault: it is tried again on the next pass.
                    log.warning("photos: Immich could not give a photo, the rest waits: %s", exc)
                    stopped = True
                    report.waiting[album.id] = report.waiting.get(album.id, 0) + 1
                    continue
            except PhotoError as exc:
                log.warning("photo %s could not be read for slideshows: %s", photo.id, exc)
                look = None
            if look is None:
                report.unreadable += 1
                await registry.save_photo_look(photo.id, checksum, version, {}, failed=True)
            else:
                report.looked += 1
                if _is_preview(look, photo):
                    report.previews += 1
                await registry.save_photo_look(photo.id, checksum, version, look.to_dict())
            done.add(photo.id)
            # Each look is kept at once: the work of a long pass is not lost if it stops.
            await registry.commit()
    return report


async def _look(immich: ImmichClient, context: SlideshowContext, photo: Asset) -> PhotoLook:
    content, _ = await immich.photo(photo.id, full=context.full)
    return await context.look(photo.id, content)


def _transient(exc: ImmichError) -> bool:
    """An error of Immich or of the way to it, not of the photo: worth another try later."""
    return (
        isinstance(exc, ImmichUnreachableError)
        or exc.status is None
        or exc.status >= 500
        or (exc.status in (401, 403, 429))
    )


def _is_preview(look: PhotoLook, photo: Asset) -> bool:
    side = max(photo.width or 0, photo.height or 0)
    return side > 0 and look.given_side < side * PREVIEW_SHARE


__all__ = ["PhotoReport", "SlideshowContext", "look_at_photos"]
