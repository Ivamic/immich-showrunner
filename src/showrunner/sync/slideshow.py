# SPDX-License-Identifier: AGPL-3.0-or-later
"""The slideshow step of a pass: look at the photos of the albums not looked at yet.

A photo is downloaded from Immich and looked at in the worker process (about a second for a
large one), so a large library is looked at over several passes, as videos are for artwork: each
pass stops after its time budget, and an album with photos still to look at is not stamped, so
that the next quick pass comes back to it.

Photos are looked at in full size when the key may download them; otherwise, and for HEIC or RAW
when Immich makes no full-size pictures, the preview of Immich is what there is.

The embedding of a photo needs the CLIP model, downloaded on the first photo to look at. Without
it (no data folder, no network) a photo is looked at all the same and gets its embedding on a
later full pass, once the model is there."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

from showrunner.artwork.worker import ArtworkWorker, photo_look_task, shared_worker
from showrunner.immich.client import ImmichClient, ImmichError, ImmichUnreachableError
from showrunner.immich.models import Album, Asset
from showrunner.slideshow.embed import unpack
from showrunner.slideshow.models import CLIP, ensure
from showrunner.slideshow.photos import PhotoError, PhotoLook, look_version
from showrunner.slideshow.plan import PlanPhoto
from showrunner.store.models import PhotoLookRow
from showrunner.store.registry import Registry

log = logging.getLogger(__name__)

PREVIEW_SHARE = 0.9
"""A picture with a long side below this share of the photo's is a preview, not the photo."""


@dataclass
class SlideshowContext:
    """What the slideshow step needs. The slow work runs in the worker process."""

    full: bool
    """The key may download: photos are looked at in full size."""
    data_dir: Path | None = None
    """Where models are kept; without it photos get no embeddings."""
    budget_seconds: float = 240.0
    worker: ArtworkWorker = field(default_factory=shared_worker)
    clock: Callable[[], float] = time.monotonic

    async def model(self) -> Path | None:
        """The CLIP model, downloaded when it is missing; None when it can not be had now."""
        return await ensure(CLIP, self.data_dir)

    async def look(
        self, asset_id: UUID, content: bytes, model: Path | None
    ) -> tuple[PhotoLook, bytes | None]:
        """The look of a photo and its embedding (with a model). Raises PhotoError."""
        data, embedding = await self.worker.run(
            photo_look_task, str(asset_id), content, str(model) if model is not None else None
        )
        found = PhotoLook.from_dict(data)
        if found is None:  # pragma: no cover - the worker runs the same code
            raise PhotoError("the worker made a look of another version")
        return found, embedding


@dataclass
class PhotoReport:
    looked: int = 0
    unreadable: int = 0
    # Photos that came smaller than they are: previews instead of the photos.
    previews: int = 0
    # Photos looked at without an embedding: the model is not there.
    without_embedding: int = 0
    # Albums with photos still to look at, and how many.
    waiting: dict[UUID, int] = field(default_factory=dict)
    # The photos of each album read, as Immich gave them.
    photos: dict[UUID, list[Asset]] = field(default_factory=dict)

    @property
    def incomplete(self) -> set[UUID]:
        return set(self.waiting)


class _Model:
    """The model, asked for once per pass and only when a photo needs it."""

    def __init__(self, context: SlideshowContext) -> None:
        self._context = context
        self._asked = False
        self.path: Path | None = None

    async def get(self) -> Path | None:
        if not self._asked:
            self._asked = True
            self.path = await self._context.model()
        return self.path


async def look_at_photos(
    immich: ImmichClient,
    albums: Sequence[Album],
    registry: Registry,
    context: SlideshowContext,
) -> PhotoReport:
    """Look at the photos of `albums` that have no look of this version for their checksum, or no
    embedding of the current model while it is there. Raises ImmichError when an album can not be
    listed (the pass stops, as for videos)."""
    report = PhotoReport()
    photos = report.photos
    for album in albums:
        photos[album.id] = [photo async for photo in immich.album_photos(album.id)]
    ids = {photo.id for every in photos.values() for photo in every}
    rows = await registry.photo_looks(ids)
    version = look_version()
    model = _Model(context)
    started = context.clock()
    done: set[UUID] = set()
    stopped = False
    for album in albums:
        for photo in photos[album.id]:
            row = rows.get(photo.id)
            checksum = photo_key(photo)
            if photo.id in done:
                continue
            fresh = _fresh(row, checksum, version)
            if fresh and (row is None or row.failed or row.embedding_model == CLIP.id):
                continue
            if fresh and await model.get() is None:
                continue  # only the embedding is missing, and the model is not there
            if stopped or context.clock() - started >= context.budget_seconds:
                stopped = True
                if not fresh:
                    report.waiting[album.id] = report.waiting.get(album.id, 0) + 1
                continue
            path = await model.get()
            try:
                content, _ = await immich.photo(photo.id, full=context.full, edited=photo.is_edited)
                found, embedding = await context.look(photo.id, content, path)
            except ImmichError as exc:
                if _transient(exc):
                    # Not the photo's fault: it is tried again on the next pass.
                    log.warning("photos: Immich could not give a photo, the rest waits: %s", exc)
                    stopped = True
                    if not fresh:
                        report.waiting[album.id] = report.waiting.get(album.id, 0) + 1
                    continue
                log.warning("photo %s could not be read for slideshows: %s", photo.id, exc)
                found, embedding = None, None
            except PhotoError as exc:
                log.warning("photo %s could not be read for slideshows: %s", photo.id, exc)
                found, embedding = None, None
            if found is None:
                report.unreadable += 1
                await registry.save_photo_look(photo.id, checksum, version, {}, failed=True)
            else:
                report.looked += 1
                if _is_preview(found, photo):
                    report.previews += 1
                if embedding is None:
                    report.without_embedding += 1
                await registry.save_photo_look(
                    photo.id,
                    checksum,
                    version,
                    found.to_dict(),
                    embedding=embedding,
                    embedding_model=CLIP.id if embedding is not None else None,
                )
            done.add(photo.id)
            # Each look is kept at once: the work of a long pass is not lost if it stops.
            await registry.commit()
    return report


def plan_inputs(photos: Sequence[Asset], rows: Mapping[UUID, PhotoLookRow]) -> list[PlanPhoto]:
    """The photos of an album as the cut list needs them: those looked at, by this version and
    for their checksum, and readable. The embedding goes along when it is of the current model."""
    version = look_version()
    result: list[PlanPhoto] = []
    for photo in photos:
        row = rows.get(photo.id)
        if row is None or row.failed or not _fresh(row, photo_key(photo), version):
            continue
        look = PhotoLook.from_dict(row.look)
        if look is None:
            continue
        embedding = (
            unpack(row.embedding)
            if row.embedding is not None and row.embedding_model == CLIP.id
            else None
        )
        exif = photo.exif_info
        result.append(
            PlanPhoto(
                asset_id=photo.id,
                taken=photo.local_date_time.replace(tzinfo=None),
                look=look,
                latitude=exif.latitude if exif else None,
                longitude=exif.longitude if exif else None,
                embedding=embedding,
                edit=(photo.thumbhash or "edited") if photo.is_edited else "",
                city=(exif.city or "") if exif else "",
                country=(exif.country or "") if exif else "",
            )
        )
    return result


def photo_key(photo: Asset) -> str:
    """What the look of a photo is kept for: its file, and its edit in Immich when it has one
    (the thumbhash changes with each edit and comes back when the edit is undone)."""
    checksum = photo.checksum or ""
    return f"{checksum}/{photo.thumbhash or ''}" if photo.is_edited else checksum


def _fresh(row: PhotoLookRow | None, checksum: str, version: int) -> bool:
    return row is not None and row.checksum == checksum and row.version == version


def _transient(exc: ImmichError) -> bool:
    """An error of Immich or of the way to it, not of the photo: worth another try later."""
    if isinstance(exc, ImmichUnreachableError) or exc.status is None:
        return True
    return exc.status >= 500 or exc.status in (401, 403, 429)


def _is_preview(look: PhotoLook, photo: Asset) -> bool:
    side = max(photo.width or 0, photo.height or 0)
    return side > 0 and look.given_side < side * PREVIEW_SHARE


__all__ = ["PhotoReport", "SlideshowContext", "look_at_photos", "plan_inputs"]
