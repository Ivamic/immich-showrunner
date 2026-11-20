# SPDX-License-Identifier: AGPL-3.0-or-later
"""Looking at a photo for a slideshow: how good it is, its faces, where to move the camera to,
and a perceptual hash to tell near copies of it.

A photo is looked at once, as a frame of a video is for artwork: the look is kept (by asset and
checksum), the pixels are not; a photo chosen for a slideshow is downloaded again when the
slideshow is made. The look of a photo is the look of a frame (`FrameLook`, so a photo counts
for artwork the same way) with what only photos need on top."""

from __future__ import annotations

import io
import warnings
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from showrunner.artwork.faces import FaceDetector
from showrunner.artwork.select import LOOK_VERSION as FRAME_LOOK_VERSION
from showrunner.artwork.select import FrameLook, look

PHOTO_LOOK_VERSION = 1
"""Raised when the way photos are looked at changes, so kept looks are made again."""
WORK_SIDE = 1280
"""Long side a photo is looked at in: enough for faces and quality, quick to decode."""
HASH_SIDE = 32
MAX_PIXELS = 400_000_000
"""Larger photos (a huge panorama) are not opened: decoding them would take gigabytes."""


class PhotoError(ValueError):
    """The content can not be read as a photo."""


@dataclass(frozen=True)
class PhotoLook:
    frame: FrameLook
    """Quality, faces, focus and the tiny copy, as for a frame of a video (at 0)."""
    width: int
    height: int
    """Size of the picture that was looked at, turned upright."""
    given_side: int
    """Long side of the picture Immich gave: smaller than the photo when it was a preview."""
    phash: int
    """63-bit perceptual hash (DCT): near copies of a photo differ in a few bits."""

    @property
    def asset_id(self) -> str:
        return self.frame.asset_id

    @property
    def score(self) -> float:
        return self.frame.score

    def to_dict(self) -> dict[str, Any]:
        return {
            "v": PHOTO_LOOK_VERSION,
            "frame": self.frame.to_dict(),
            "width": self.width,
            "height": self.height,
            "given_side": self.given_side,
            "phash": f"{self.phash:016x}",
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PhotoLook | None:
        """None for a look made by another version (of photos or of frames): it is to be made
        again."""
        if data.get("v") != PHOTO_LOOK_VERSION:
            return None
        frame = FrameLook.from_dict(data["frame"])
        if frame is None:
            return None
        return cls(
            frame=frame,
            width=int(data["width"]),
            height=int(data["height"]),
            given_side=int(data["given_side"]),
            phash=int(data["phash"], 16),
        )


def look_version() -> int:
    """The version kept with a look: changes when either photos or frames are looked at
    differently."""
    return PHOTO_LOOK_VERSION * 1000 + FRAME_LOOK_VERSION


def open_photo(content: bytes, long_side: int = WORK_SIDE) -> tuple[Image.Image, int]:
    """The photo, upright and in RGB, about `long_side` large or smaller, and the long side of
    the picture as given. JPEG is decoded at a reduced scale straight away, which is several
    times quicker for a large photo. Raises PhotoError."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            source = Image.open(io.BytesIO(content))
            if source.width * source.height > MAX_PIXELS:
                raise PhotoError(f"it is too large ({source.width}x{source.height})")
            given_side = max(source.size)
            # The size on the disk, not the turned one: draft scales by a power of two and keeps
            # at least the size asked for.
            source.draft("RGB", (long_side, long_side))
            source.load()
            upright = ImageOps.exif_transpose(source)
    except PhotoError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombWarning) as exc:
        raise PhotoError(f"it could not be read as a photo: {exc}") from exc
    except Image.DecompressionBombError as exc:
        raise PhotoError(f"it is too large: {exc}") from exc
    picture = _rgb(upright)
    if max(picture.size) > long_side:
        picture.thumbnail((long_side, long_side), Image.Resampling.LANCZOS)
    return picture, given_side


def look_at_photo(asset_id: str, content: bytes, detector: FaceDetector) -> PhotoLook:
    """Look at one photo. Blocking: run it in the worker. Raises PhotoError."""
    picture, given_side = open_photo(content)
    return PhotoLook(
        frame=look(asset_id, 0.0, picture, detector),
        width=picture.width,
        height=picture.height,
        given_side=given_side,
        phash=phash(picture),
    )


def phash(image: Image.Image) -> int:
    """The DCT perceptual hash: the low frequencies of the grey picture, each bit telling
    whether one is above their median."""
    grey = np.asarray(
        image.convert("L").resize((HASH_SIDE, HASH_SIDE), Image.Resampling.LANCZOS),
        dtype=np.float32,
    )
    low = cv2.dct(grey)[:8, :8].reshape(-1)
    # The first coefficient is the overall brightness: it says nothing of the layout.
    bits = low[1:] > np.median(low[1:])
    value = 0
    for bit in bits:
        value = (value << 1) | int(bit)
    return value


def distance(a: int, b: int) -> int:
    """How many bits two hashes differ in: 0 for the same picture, about 32 for unlike ones."""
    return (a ^ b).bit_count()


def _rgb(picture: Image.Image) -> Image.Image:
    if picture.mode == "RGB":
        return picture
    if picture.mode in ("RGBA", "LA", "PA") or "transparency" in picture.info:
        rgba = picture.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    return picture.convert("RGB")
