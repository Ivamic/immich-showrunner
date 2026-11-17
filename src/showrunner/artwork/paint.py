# SPDX-License-Identifier: AGPL-3.0-or-later
"""Drawing primitives: backgrounds, framed cells, fixed pictures, text and its plate.

Everything is drawn in RGBA at the real size. Shapes are drawn four times larger and
scaled down, so their edges are smooth. Nothing here is random: the jitter of attachments
comes from a generator the caller seeds."""

from __future__ import annotations

import itertools
import math
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageOps

from showrunner.artwork.style import (
    Background,
    CellStyle,
    LinearGradient,
    Plate,
    RadialSpot,
    Shadow,
    Stop,
    TextBlock,
    Texture,
)
from showrunner.artwork.text import FittedText, font

SUPERSAMPLE = 4
RADIAL_EDGE = 181
RESAMPLE = Image.Resampling.LANCZOS
Rect = tuple[float, float, float, float]
"""left, top, width, height in pixels."""
AssetResolver = Callable[[str], Path]
"""The file of a style's asset by the name used in `style.yaml`."""


@dataclass(frozen=True)
class Frame:
    """A frame of a video and the point that matters most in it (shares of width and height),
    which stays in view when the frame is cropped."""

    image: Image.Image
    focus: tuple[float, float] = (0.5, 0.5)


def rgba(color: str) -> tuple[int, int, int, int]:
    value = color.lstrip("#")
    alpha = int(value[6:8], 16) if len(value) == 8 else 255
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16), alpha


@lru_cache(maxsize=32)
def asset(path: Path) -> Image.Image:
    with Image.open(path) as picture:
        return picture.convert("RGBA")


# --- background -------------------------------------------------------------------------


def background(size: tuple[int, int], spec: Background, assets: AssetResolver) -> Image.Image:
    canvas = Image.new("RGBA", size, rgba(spec.color))
    for layer in spec.layers:
        if isinstance(layer, LinearGradient):
            canvas.alpha_composite(linear_gradient(size, layer))
        elif isinstance(layer, RadialSpot):
            canvas.alpha_composite(radial_spot(size, layer))
        elif isinstance(layer, Texture):
            texture = cover(asset(assets(layer.image)), size, (0.5, 0.5))
            if layer.opacity < 1:
                table = [round(a * layer.opacity) for a in range(256)]
                texture.putalpha(texture.getchannel("A").point(table))
            canvas.alpha_composite(texture)
    return canvas


def linear_gradient(size: tuple[int, int], spec: LinearGradient) -> Image.Image:
    """A gradient along a CSS angle; the gradient line is as long as in CSS, so the first
    and the last stop touch the corners."""
    width, height = size
    angle = math.radians(spec.angle)
    length = max(1.0, abs(width * math.sin(angle)) + abs(height * math.cos(angle)))
    side = math.ceil(math.hypot(width, height)) + 2
    # A ramp running downwards (the CSS angle 180) over `length` pixels in the middle ...
    column = Image.new("L", (1, side))
    start = (side - length) / 2
    column.putdata([min(255, max(0, round((row - start) / length * 255))) for row in range(side)])
    ramp = column.resize((side, side), Image.Resampling.NEAREST)
    # ... turned to the angle and cut to the picture.
    ramp = ramp.rotate(180 - spec.angle, resample=Image.Resampling.BILINEAR, fillcolor=0)
    left, top = (side - width) // 2, (side - height) // 2
    ramp = ramp.crop((left, top, left + width, top + height))
    stops = sorted(spec.stops, key=lambda stop: stop.at)
    table = [_between(stops, i / 255) for i in range(256)]
    return Image.merge("RGBA", [ramp.point([color[c] for color in table]) for c in range(4)])


def _between(stops: Sequence[Stop], at: float) -> tuple[int, int, int, int]:
    if at <= stops[0].at:
        return rgba(stops[0].color)
    for left, right in itertools.pairwise(stops):
        if at <= right.at:
            t = (at - left.at) / max(1e-9, right.at - left.at)
            a, b = rgba(left.color), rgba(right.color)
            return (
                round(a[0] + (b[0] - a[0]) * t),
                round(a[1] + (b[1] - a[1]) * t),
                round(a[2] + (b[2] - a[2]) * t),
                round(a[3] + (b[3] - a[3]) * t),
            )
    return rgba(stops[-1].color)


def radial_spot(size: tuple[int, int], spec: RadialSpot) -> Image.Image:
    width, height = size
    radius = spec.radius / 100 * width
    diameter = max(2, round(radius * 2))
    r, g, b, a = rgba(spec.color)
    # Pillow's radial gradient is 0 in the middle and RADIAL_EDGE at the middle of each side
    # (255 only in the corners); the spot must be gone at the radius, so past it is clear.
    falloff = Image.radial_gradient("L").point(
        [round(max(0.0, 1 - v / RADIAL_EDGE) * a) for v in range(256)]
    )
    spot = Image.new("RGBA", (diameter, diameter), (r, g, b, 0))
    spot.putalpha(falloff.resize((diameter, diameter), RESAMPLE))
    layer = Image.new("RGBA", size, (r, g, b, 0))
    cx, cy = spec.center[0] / 100 * width, spec.center[1] / 100 * height
    _paste_clipped(layer, spot, cx - radius, cy - radius)
    return layer


def _paste_clipped(canvas: Image.Image, piece: Image.Image, x: float, y: float) -> None:
    """alpha_composite that allows the piece to stick out of the canvas on any side."""
    left, top = round(x), round(y)
    box = (
        max(0, -left),
        max(0, -top),
        min(piece.width, canvas.width - left),
        min(piece.height, canvas.height - top),
    )
    if box[0] >= box[2] or box[1] >= box[3]:
        return
    canvas.alpha_composite(piece.crop(box), dest=(left + box[0], top + box[1]))


def place(canvas: Image.Image, piece: Image.Image, center: tuple[float, float]) -> None:
    _paste_clipped(canvas, piece, center[0] - piece.width / 2, center[1] - piece.height / 2)


# --- frames in cells --------------------------------------------------------------------


def cover(image: Image.Image, size: tuple[int, int], focus: tuple[float, float]) -> Image.Image:
    """Scale to fill the size and crop, keeping the focus point in view (CSS object-position)."""
    width, height = max(1, size[0]), max(1, size[1])
    scale = max(width / image.width, height / image.height)
    scaled = (max(width, round(image.width * scale)), max(height, round(image.height * scale)))
    left = (scaled[0] - width) * min(1, max(0, focus[0]))
    top = (scaled[1] - height) * min(1, max(0, focus[1]))
    # Crop in the source first, so a large frame is not scaled whole.
    box = (left / scale, top / scale, (left + width) / scale, (top + height) / scale)
    return image.convert("RGBA").resize((width, height), RESAMPLE, box=box)


def filtered(image: Image.Image, style: CellStyle, scale: float) -> Image.Image:
    spec = style.filter
    if spec is None:
        return image
    alpha = image.getchannel("A")
    rgb = image.convert("RGB")
    if spec.grayscale:
        rgb = ImageOps.grayscale(rgb).convert("RGB")
    if spec.saturation != 1:
        rgb = ImageEnhance.Color(rgb).enhance(spec.saturation)
    if spec.contrast != 1:
        rgb = ImageEnhance.Contrast(rgb).enhance(spec.contrast)
    if spec.brightness != 1:
        rgb = ImageEnhance.Brightness(rgb).enhance(spec.brightness)
    if spec.blur:
        rgb = rgb.filter(ImageFilter.GaussianBlur(spec.blur * scale))
    rgb.putalpha(alpha)
    return rgb


def shape_mask(
    size: tuple[int, int], style: CellStyle, scale: float, assets: AssetResolver
) -> Image.Image:
    width, height = size
    if style.shape == "mask" and style.mask:
        source = asset(assets(style.mask))
        has_alpha = source.getchannel("A").getextrema() != (255, 255)
        channel = source.getchannel("A") if has_alpha else source.convert("L")
        return channel.resize(size, RESAMPLE)
    big = (width * SUPERSAMPLE, height * SUPERSAMPLE)
    mask = Image.new("L", big, 0)
    draw = ImageDraw.Draw(mask)
    bw, bh = big[0] - 1, big[1] - 1
    if style.shape == "circle":
        draw.ellipse((0, 0, bw, bh), fill=255)
    elif style.shape == "diamond":
        draw.polygon([(bw / 2, 0), (bw, bh / 2), (bw / 2, bh), (0, bh / 2)], fill=255)
    elif style.shape == "polygon" and style.points:
        draw.polygon([(x / 100 * bw, y / 100 * bh) for x, y in style.points], fill=255)
    else:
        radius = style.radius * scale * SUPERSAMPLE
        draw.rounded_rectangle((0, 0, bw, bh), radius=radius, fill=255)
    return mask.resize(size, RESAMPLE)


def cell_piece(
    frame: Frame,
    size: tuple[int, int],
    style: CellStyle,
    scale: float,
    assets: AssetResolver,
    rng: random.Random,
) -> tuple[Image.Image, tuple[float, float]]:
    """A framed frame with its attachments, on a transparent margin; and where the cell's
    middle is in it."""
    width, height = max(1, size[0]), max(1, size[1])
    tile = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    mat = style.mat
    if mat is not None:
        tile.paste(rgba(mat.color), (0, 0, width, height))
        left, top = round(mat.left * scale), round(mat.top * scale)
        inner = (
            max(1, width - left - round(mat.right * scale)),
            max(1, height - top - round(mat.bottom * scale)),
        )
    else:
        left, top, inner = 0, 0, (width, height)
    picture = filtered(cover(frame.image, inner, frame.focus), style, scale)
    tile.alpha_composite(picture, dest=(left, top))
    if style.border is not None:
        line = max(1, round(style.border.width * scale))
        ImageDraw.Draw(tile).rectangle(
            (0, 0, width - 1, height - 1), outline=rgba(style.border.color), width=line
        )
    if style.shape != "rect" or style.radius:
        tile.putalpha(
            ImageChops.multiply(
                tile.getchannel("A"), shape_mask((width, height), style, scale, assets)
            )
        )

    # Room around the tile for attachments that stick out.
    margin = round(max(width, height) * 0.25) if style.attachments else 0
    piece = Image.new("RGBA", (width + 2 * margin, height + 2 * margin), (0, 0, 0, 0))
    piece.alpha_composite(tile, dest=(margin, margin))
    for attachment in style.attachments:
        source = asset(assets(attachment.image))
        aw = max(1, round(width * attachment.width / 100))
        ah = max(1, round(source.height * aw / source.width))
        stuck = source.resize((aw, ah), RESAMPLE)
        turn = rng.uniform(-attachment.jitter, attachment.jitter) if attachment.jitter else 0.0
        if turn:
            stuck = stuck.rotate(turn, resample=Image.Resampling.BICUBIC, expand=True)
        x = {"top_left": width * 0.12, "top_right": width * 0.88}.get(attachment.anchor, width / 2)
        y = height if attachment.anchor == "bottom" else 0
        place(piece, stuck, (margin + x, margin + y))
    return piece, (piece.width / 2, piece.height / 2)


def with_shadow(
    piece: Image.Image, shadow: Shadow | None, scale: float
) -> tuple[Image.Image, tuple[float, float]]:
    """The piece over its shadow; and the shift of the piece's middle in the result."""
    if shadow is None:
        return piece, (0.0, 0.0)
    blur = shadow.blur * scale
    pad = round(blur * 2 + max(abs(shadow.dx), abs(shadow.dy)) * scale) + 1
    out = Image.new("RGBA", (piece.width + 2 * pad, piece.height + 2 * pad), (0, 0, 0, 0))
    r, g, b, a = rgba(shadow.color)
    alpha = piece.getchannel("A").point(lambda v: round(v * a / 255))
    dark = Image.new("RGBA", piece.size, (r, g, b, 0))
    dark.putalpha(alpha)
    out.alpha_composite(dark, dest=(pad + round(shadow.dx * scale), pad + round(shadow.dy * scale)))
    if blur:
        out = out.filter(ImageFilter.GaussianBlur(blur))
    out.alpha_composite(piece, dest=(pad, pad))
    return out, (0.0, 0.0)


def draw_cell(
    canvas: Image.Image,
    frame: Frame,
    rect: Rect,
    rotate: float,
    style: CellStyle,
    scale: float,
    assets: AssetResolver,
    rng: random.Random,
) -> None:
    x, y, w, h = rect
    # Whole pixels at both edges, so cells of a grid meet without seams.
    left, top, right, bottom = round(x), round(y), round(x + w), round(y + h)
    piece, _ = cell_piece(frame, (right - left, bottom - top), style, scale, assets, rng)
    if rotate:
        piece = piece.rotate(-rotate, resample=Image.Resampling.BICUBIC, expand=True)
    piece, _ = with_shadow(piece, style.shadow, scale)
    place(canvas, piece, ((left + right) / 2, (top + bottom) / 2))


def draw_decor(canvas: Image.Image, image: Path, rect: Rect, rotate: float) -> None:
    x, y, w, h = rect
    picture = asset(image).resize((max(1, round(w)), max(1, round(h))), RESAMPLE)
    if rotate:
        picture = picture.rotate(-rotate, resample=Image.Resampling.BICUBIC, expand=True)
    place(canvas, picture, (x + w / 2, y + h / 2))


# --- text -------------------------------------------------------------------------------


def draw_text(
    canvas: Image.Image,
    fitted: FittedText,
    spec: TextBlock,
    area: Rect,
    font_file: tuple[Path, int],
    scale: float,
) -> None:
    if not fitted.lines:
        return
    face = font(font_file[0], fitted.size, font_file[1])
    ascent, descent = face.getmetrics()
    pitch = fitted.size * spec.line_height
    block_height = pitch * (len(fitted.lines) - 1) + ascent + descent
    x, y, w, h = area
    top = {"top": y, "center": y + (h - block_height) / 2, "bottom": y + h - block_height}[
        spec.anchor
    ]
    widths = [face.getlength(line) for line in fitted.lines]
    starts = [
        {"left": x, "center": x + (w - lw) / 2, "right": x + w - lw}[spec.align] for lw in widths
    ]

    if spec.plate is not None:
        _plate(canvas, spec.plate, (min(starts), top, max(widths), block_height), scale)

    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    stroke = round(spec.stroke.width * scale) if spec.stroke else 0
    stroke_fill = rgba(spec.stroke.color) if spec.stroke else None
    for i, line in enumerate(fitted.lines):
        draw.text(
            (starts[i], top + pitch * i),
            line,
            font=face,
            fill=rgba(spec.color),
            stroke_width=stroke,
            stroke_fill=stroke_fill,
        )
    if spec.shadow is not None:
        shadow, _ = with_shadow(layer, spec.shadow, scale)
        pad = (shadow.width - layer.width) // 2
        canvas.alpha_composite(shadow.crop((pad, pad, pad + canvas.width, pad + canvas.height)))
    else:
        canvas.alpha_composite(layer)


def _plate(canvas: Image.Image, spec: Plate, text: Rect, scale: float) -> None:
    width, height = canvas.size
    x, y, w, h = text
    pad_top, pad_x, pad_bottom = spec.pad_top * scale, spec.pad_x * scale, spec.pad_bottom * scale
    r, g, b, a = rgba(spec.color)
    if spec.kind == "fade":
        solid_top = max(0, y - pad_top)
        fade = spec.fade * scale
        top = max(0, solid_top - fade)
        rows = max(1, height - round(top))
        column = Image.new("L", (1, rows))
        for i in range(rows):
            at = round(top) + i
            if at < solid_top:  # fading in from nothing to fade_from
                share = (at - top) / max(1.0, solid_top - top) * spec.fade_from
            else:  # from fade_from at the top of the solid part to full at the bottom
                share = spec.fade_from + (1 - spec.fade_from) * (at - solid_top) / max(
                    1.0, height - solid_top
                )
            column.putpixel((0, i), round(a * share))
        plate = Image.new("RGBA", (width, rows), (r, g, b, 0))
        plate.putalpha(column.resize((width, rows)))
        canvas.alpha_composite(plate, dest=(0, round(top)))
        return
    if spec.kind == "band":
        box = (0.0, y - pad_top, float(width), y + h + pad_bottom)
    else:
        box = (x - pad_x, y - pad_top, x + w + pad_x, y + h + pad_bottom)
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle(box, radius=spec.radius * scale, fill=(r, g, b, a))
    canvas.alpha_composite(layer)
