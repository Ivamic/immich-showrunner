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

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

from showrunner.artwork.style import (
    Background,
    BackgroundLayer,
    CellStyle,
    Decor,
    FontFile,
    LinearGradient,
    Plate,
    RadialSpot,
    Shadow,
    Stop,
    TextBlock,
    Texture,
    Vignette,
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
    """A frame of a video, the point that matters most in it and the region to keep whole
    (faces), as shares of width and height; both guide the crop to a cell."""

    image: Image.Image
    focus: tuple[float, float] = (0.5, 0.5)
    region: tuple[float, float, float, float] | None = None


def rgba(color: str) -> tuple[int, int, int, int]:
    value = color.lstrip("#")
    alpha = int(value[6:8], 16) if len(value) == 8 else 255
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16), alpha


@lru_cache(maxsize=32)
def asset(path: Path) -> Image.Image:
    with Image.open(path) as picture:
        return picture.convert("RGBA")


# --- background -------------------------------------------------------------------------


def background(
    size: tuple[int, int], spec: Background, assets: AssetResolver, scale: float = 1.0
) -> Image.Image:
    canvas = Image.new("RGBA", size, rgba(spec.color))
    draw_layers(canvas, spec.layers, assets, scale)
    return canvas


def draw_layers(
    canvas: Image.Image, layers: Sequence[BackgroundLayer], assets: AssetResolver, scale: float
) -> None:
    size = canvas.size
    for layer in layers:
        if isinstance(layer, LinearGradient):
            canvas.alpha_composite(linear_gradient(size, layer))
        elif isinstance(layer, RadialSpot):
            canvas.alpha_composite(radial_spot(size, layer))
        elif isinstance(layer, Vignette):
            canvas.alpha_composite(vignette(size, layer))
        elif isinstance(layer, Texture):
            source = asset(assets(layer.image))
            if layer.tile:
                texture = tiled(source, size, layer.tile * scale)
            else:
                texture = cover(source, size, (0.5, 0.5))
            if layer.opacity < 1:
                table = [round(a * layer.opacity) for a in range(256)]
                texture.putalpha(texture.getchannel("A").point(table))
            canvas.alpha_composite(texture)


def tiled(
    source: Image.Image, size: tuple[int, int], tile_width: float, tile_height: float | None = None
) -> Image.Image:
    """The picture repeated over the size, each tile `tile_width` pixels wide."""
    tw = max(1, round(tile_width))
    th = max(1, round(tile_height if tile_height else source.height * tw / source.width))
    tile = source.resize((tw, th), RESAMPLE)
    out = Image.new("RGBA", size, (0, 0, 0, 0))
    for top in range(0, size[1], th):
        for left in range(0, size[0], tw):
            out.paste(tile, (left, top))
    return out


def vignette(size: tuple[int, int], spec: Vignette) -> Image.Image:
    r, g, b, a = rgba(spec.color)
    # Distance from the middle as a share of the way to the corner (an ellipse over the
    # picture); Pillow's radial gradient is 255 in the corners.
    distance = Image.radial_gradient("L").resize(size, Image.Resampling.BILINEAR)
    inner = spec.inner * 255
    table = [round(min(1.0, max(0.0, (v - inner) / (255 - inner))) * a) for v in range(256)]
    layer = Image.new("RGBA", size, (r, g, b, 0))
    layer.putalpha(distance.point(table))
    return layer


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


def cover(
    image: Image.Image,
    size: tuple[int, int],
    focus: tuple[float, float] = (0.5, 0.5),
    region: tuple[float, float, float, float] | None = None,
) -> Image.Image:
    """Scale to fill the size and crop. The focus point goes as near the middle of the crop as
    the edges allow; the region (faces), when it fits, stays whole."""
    width, height = max(1, size[0]), max(1, size[1])
    scale = max(width / image.width, height / image.height)
    full = (image.width * scale, image.height * scale)
    spans = (region[0], region[0] + region[2]) if region else None
    left = _offset(full[0], width, focus[0], spans)
    spans = (region[1], region[1] + region[3]) if region else None
    top = _offset(full[1], height, focus[1], spans)
    # Crop in the source first, so a large frame is not scaled whole.
    box = (left / scale, top / scale, (left + width) / scale, (top + height) / scale)
    return image.convert("RGBA").resize((width, height), RESAMPLE, box=box)


def _offset(total: float, window: float, point: float, keep: tuple[float, float] | None) -> float:
    """Start of the crop window along one side, in scaled pixels."""
    offset = point * total - window / 2
    if keep is not None:
        start, end = keep[0] * total, keep[1] * total
        if end - start <= window:
            offset = min(max(offset, end - window), start)
        else:
            offset = (start + end) / 2 - window / 2
    return min(max(offset, 0.0), max(0.0, total - window))


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
    picture = filtered(cover(frame.image, inner, frame.focus, frame.region), style, scale)
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
        turn = attachment.turn
        if attachment.jitter:
            turn += rng.uniform(-attachment.jitter, attachment.jitter)
        if turn:
            stuck = stuck.rotate(-turn, resample=Image.Resampling.BICUBIC, expand=True)
        x = {"top_left": width * 0.12, "top_right": width * 0.88}.get(attachment.anchor, width / 2)
        y = (height if attachment.anchor == "bottom" else 0) + height * attachment.dy / 100
        place(piece, stuck, (margin + x, margin + y))
    return piece, (piece.width / 2, piece.height / 2)


def with_shadow(
    piece: Image.Image, shadow: Shadow | None, scale: float
) -> tuple[Image.Image, tuple[float, float]]:
    """The piece over its shadow; and the shift of the piece's middle in the result."""
    if shadow is None:
        return piece, (0.0, 0.0)
    blur = shadow.blur * scale / 2  # a CSS blur radius is twice the Gaussian deviation
    pad = round(blur * 3 + max(abs(shadow.dx), abs(shadow.dy)) * scale) + 1
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


def draw_decor(
    canvas: Image.Image, spec: Decor, rect: Rect, scale: float, assets: AssetResolver
) -> None:
    x, y, w, h = rect
    size = (max(1, round(w)), max(1, round(h)))
    if spec.color is not None:
        picture = Image.new("RGBA", size, rgba(spec.color))
    elif spec.tile is not None and spec.image:
        picture = tiled(asset(assets(spec.image)), size, spec.tile[0] * scale, spec.tile[1] * scale)
    elif spec.image:
        picture = asset(assets(spec.image)).resize(size, RESAMPLE)
    else:
        return
    if spec.radius:
        mask = Image.new("L", (size[0] * SUPERSAMPLE, size[1] * SUPERSAMPLE), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            (0, 0, mask.width - 1, mask.height - 1),
            radius=spec.radius * scale * SUPERSAMPLE,
            fill=255,
        )
        picture.putalpha(ImageChops.multiply(picture.getchannel("A"), mask.resize(size, RESAMPLE)))
    if spec.rotate:
        picture = picture.rotate(-spec.rotate, resample=Image.Resampling.BICUBIC, expand=True)
    picture, _ = with_shadow(picture, spec.shadow, scale)
    place(canvas, picture, (x + w / 2, y + h / 2))


# --- text -------------------------------------------------------------------------------


def draw_text(
    canvas: Image.Image,
    fitted: FittedText,
    spec: TextBlock,
    area: Rect,
    font_file: FontFile,
    scale: float,
    assets: AssetResolver,
) -> None:
    """The lines on their plate. Text and plate are drawn on their own layer first, so the
    whole block can be turned and cast one shadow."""
    if not fitted.lines:
        return
    face = font(font_file.path, fitted.size, font_file.index, font_file.variation)
    spacing = spec.letter_spacing * fitted.size
    ascent, descent = face.getmetrics()
    pitch = fitted.size * spec.line_height
    block_height = pitch * (len(fitted.lines) - 1) + ascent + descent
    x, y, w, h = area
    top = {"top": y, "center": y + (h - block_height) / 2, "bottom": y + h - block_height}[
        spec.anchor
    ]
    widths = [_line_width(face, line, spacing) for line in fitted.lines]
    starts = [
        {"left": x, "center": x + (w - lw) / 2, "right": x + w - lw}[spec.align] for lw in widths
    ]
    text_box = (min(starts), top, max(widths), block_height)

    block = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    middle = (text_box[0] + text_box[2] / 2, text_box[1] + text_box[3] / 2)
    if spec.plate is not None:
        middle = _plate(block, spec.plate, text_box, scale, assets)

    letters = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(letters)
    stroke = round(spec.stroke.width * scale) if spec.stroke else 0
    stroke_fill = rgba(spec.stroke.color) if spec.stroke else None
    for i, line in enumerate(fitted.lines):
        at_x, at_y = starts[i], top + pitch * i
        pieces = [line] if not spacing else list(line)
        for piece in pieces:
            draw.text(
                (at_x, at_y),
                piece,
                font=face,
                fill=rgba(spec.color),
                stroke_width=stroke,
                stroke_fill=stroke_fill,
            )
            at_x += face.getlength(piece) + spacing
    if spec.shadow is not None:
        letters = _with_shadow_same_size(letters, spec.shadow, scale)
    block.alpha_composite(letters)
    if spec.rotate:
        block = block.rotate(
            -spec.rotate, resample=Image.Resampling.BICUBIC, center=middle, expand=False
        )
    canvas.alpha_composite(block)


def _line_width(face: ImageFont.FreeTypeFont, line: str, spacing: float) -> float:
    return face.getlength(line) + spacing * max(0, len(line) - 1)


def _with_shadow_same_size(layer: Image.Image, shadow: Shadow, scale: float) -> Image.Image:
    out, _ = with_shadow(layer, shadow, scale)
    pad = (out.width - layer.width) // 2
    return out.crop((pad, pad, pad + layer.width, pad + layer.height))


def _plate(
    block: Image.Image, spec: Plate, text: Rect, scale: float, assets: AssetResolver
) -> tuple[float, float]:
    """Draw the plate under the text; returns the plate's middle (the block turns around it)."""
    width, height = block.size
    x, y, w, h = text
    pad_top, pad_x, pad_bottom = spec.pad_top * scale, spec.pad_x * scale, spec.pad_bottom * scale
    r, g, b, a = rgba(spec.color)
    left, span = (0.0, float(width))
    if spec.across is not None:
        left, span = spec.across[0] / 100 * width, spec.across[1] / 100 * width
    to_edge = spec.to_edge if spec.to_edge is not None else spec.kind == "fade"
    if spec.kind in ("fade", "band"):
        solid_top = y - pad_top
        bottom = float(height) if to_edge else y + h + pad_bottom
        fade = spec.fade * scale if spec.kind == "fade" else 0.0
        top = solid_top - fade
        box = (left, top, left + span, bottom)
    else:
        box = (x - pad_x, y - pad_top, x + w + pad_x, y + h + pad_bottom)
        solid_top, fade = box[1], 0.0
    size = (max(1, round(box[2] - box[0])), max(1, round(box[3] - box[1])))
    plate = Image.new("RGBA", size, (r, g, b, a))
    if spec.image:
        plate.alpha_composite(tiled(asset(assets(spec.image)), size, spec.tile * scale))
    if spec.kind == "fade":
        column = Image.new("L", (1, size[1]))
        for i in range(size[1]):
            at = box[1] + i
            if at < solid_top:  # fading in from nothing to fade_from
                share = (at - box[1]) / max(1.0, fade) * spec.fade_from
            else:  # from fade_from at the top of the solid part to full at the bottom
                share = spec.fade_from + (1 - spec.fade_from) * (at - solid_top) / max(
                    1.0, box[3] - solid_top
                )
            column.putpixel((0, i), round(255 * min(1.0, max(0.0, share))))
        plate.putalpha(ImageChops.multiply(plate.getchannel("A"), column.resize(size)))
    if spec.radius:
        corners = Image.new("L", (size[0] * SUPERSAMPLE, size[1] * SUPERSAMPLE), 0)
        ImageDraw.Draw(corners).rounded_rectangle(
            (0, 0, corners.width - 1, corners.height - 1),
            radius=spec.radius * scale * SUPERSAMPLE,
            fill=255,
        )
        plate.putalpha(ImageChops.multiply(plate.getchannel("A"), corners.resize(size, RESAMPLE)))
    if spec.mask:
        shape = asset(assets(spec.mask)).getchannel("A").resize(size, RESAMPLE)
        plate.putalpha(ImageChops.multiply(plate.getchannel("A"), shape))
    plate, _ = with_shadow(plate, spec.shadow, scale)
    middle = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
    place(block, plate, middle)
    return middle
