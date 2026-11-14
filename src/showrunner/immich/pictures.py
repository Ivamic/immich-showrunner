# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pictures from Immich as JPEG files.

Immich can be set to make its previews as WebP, which saves space there. Kodi and some other
clients do not show WebP files next to a video, so such a preview is turned into JPEG here.
A JPEG preview is kept byte for byte."""

import io

import anyio.to_thread
from PIL import Image, UnidentifiedImageError

JPEG = "image/jpeg"
JPEG_QUALITY = 90


class PictureError(ValueError):
    """The content can not be read as a picture."""


async def as_jpeg(content: bytes, media_type: str) -> bytes:
    """The picture as JPEG: as is when it is JPEG already, converted otherwise."""
    media_type = media_type.split(";")[0].strip().lower()
    if media_type == JPEG:
        return content
    if not media_type.startswith("image/"):
        raise PictureError(f"it is {media_type or 'of no type'}, not a picture")
    return await anyio.to_thread.run_sync(_convert, content)


def _convert(content: bytes) -> bytes:
    try:
        with Image.open(io.BytesIO(content)) as source:
            source.load()
            picture: Image.Image = source
            if picture.mode != "RGB":
                picture = _on_white(picture) if _has_alpha(picture) else picture.convert("RGB")
            result = io.BytesIO()
            picture.save(result, "JPEG", quality=JPEG_QUALITY, optimize=True)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise PictureError(f"it could not be read as a picture: {exc}") from exc
    return result.getvalue()


def _has_alpha(picture: Image.Image) -> bool:
    return picture.mode in ("RGBA", "LA", "PA") or "transparency" in picture.info


def _on_white(picture: Image.Image) -> Image.Image:
    rgba = picture.convert("RGBA")
    background = Image.new("RGB", rgba.size, (255, 255, 255))
    background.paste(rgba, mask=rgba.getchannel("A"))
    return background
