# SPDX-License-Identifier: AGPL-3.0-or-later
"""One picture of a style: the background, fixed pictures under the frames, the frames in
the cells of the layout, fixed pictures over them, and the text on its plate.

The layout is the one with the most cells the frames can fill, up to the style's limit;
frames go to cells in the given order, so the best frame should come first. The jitter of
attachments comes from the seed: the same style, frames, text and seed give the same bytes."""

from __future__ import annotations

import io
import math
import random
from collections.abc import Sequence
from dataclasses import dataclass

from PIL import Image

from showrunner.artwork.paint import (
    UNDER_GAP,
    Frame,
    Rect,
    background,
    draw_cell,
    draw_decor,
    draw_layers,
    draw_text,
    place_text,
    text_extent,
)
from showrunner.artwork.style import (
    Cell,
    CellStyle,
    Grid,
    Layout,
    Output,
    OutputKind,
    Scatter,
    ScatterItem,
    Style,
    TextBlock,
    cell_style,
    text_block,
)
from showrunner.artwork.text import FittedText, Measure, fit, font_measure

JPEG_QUALITY = 90
PNG_COMPRESSION = 9


@dataclass(frozen=True)
class Rendered:
    image: Image.Image
    frames_used: int
    truncated: bool
    """The text did not fit at the smallest size and was cut with "…"."""


UNDER_SIZES = ((0.6, 1.0, 0.85), (0.45, 0.8, 0.65))
"""For each line under the text: its size in parts of the text's, the least it keeps of the
style's smallest size, and the most it may take of the text's size when the text is small."""
FRAME_GAP = 0.35
FRAME_GAP_SHARE = 0.04
"""Between the text with the lines under it and the nearest frame: a share of the text's size,
or of the picture's height when that is more."""


def render(
    style: Style,
    kind: OutputKind,
    frames: Sequence[Frame],
    text: str,
    seed: int,
    under: Sequence[str] = (),
) -> Rendered:
    """`under`: up to two smaller lines under the text, each smaller than the one before, on
    its plate (cut with an ellipsis when one does not fit across); nothing without a text."""
    output, owner = style.output(kind)
    width, height = output.size
    scale = output.scale
    rng = random.Random(f"{style.id}/{style.spec.version}/{kind}/{seed}")
    if output.background is not None:
        canvas = background(output.size, output.background, owner.path, scale)
    else:
        canvas = Image.new("RGBA", output.size, (0, 0, 0, 0))

    layout = output.layout_for(min(len(frames), style.spec.max_frames)) if frames else None

    # The title is placed first, so the frames under it can keep faces out of its way.
    spec = text_block(output, layout)
    fitted = None
    small: list[FittedText] = []
    avoid = None
    if spec is not None and text.strip():
        font_file = owner.font_path(spec.font)
        area = _rect(spec.area, width, height)
        content = text.upper() if spec.uppercase else text
        measure = font_measure(
            font_file.path, font_file.index, font_file.variation, spec.letter_spacing
        )

        def fitted_in(room: float) -> FittedText:
            return fit(
                content,
                area[2],
                spec.size[0] * scale,
                spec.size[1] * scale,
                spec.max_lines,
                measure,
                height=room,
                line_height=spec.line_height,
            )

        fitted = fitted_in(area[3])
        lines = [u.upper() if spec.uppercase else u for u in under[: len(UNDER_SIZES)] if u.strip()]
        if fitted.lines and lines:
            small = _under(lines, fitted, spec, area, scale, measure)
            # The text and the lines under it stay within the height of the tallest text the
            # style allows alone, and off the frames beside the text: a long title gets smaller
            # rather than climb over them.
            largest = spec.size[1] * scale
            tallest = largest * (spec.line_height * (spec.max_lines - 1) + 1.2)
            room = min(area[3], tallest)
            if layout is not None:
                # The cells as they will be drawn: the same jitter from a copy of the generator.
                twin = random.Random()
                twin.setstate(rng.getstate())
                boxes = [_turned(rect, turn) for rect, turn, _ in cells_of(output, layout, twin)]
                alone = place_text(fitted, spec, area, font_file).box
                room = min(room, _room_beside(boxes, alone, spec, area, fitted.size, height))
            # Fitted by the size of the letters, measured by the font: a few tries at most.
            below = sum(s.size * (1 + UNDER_GAP + 0.2) for s in small)
            target = room
            for _ in range(5):
                fitted = fitted_in(target - below)
                small = _under(lines, fitted, spec, area, scale, measure)
                taken = place_text(fitted, spec, area, font_file, small).box[3]
                if taken <= room or not fitted.lines:
                    break
                target -= taken - room + 1
        if fitted.lines and not spec.rotate:
            avoid = text_extent(place_text(fitted, spec, area, font_file, small), spec, scale)

    decor = list(output.decor) + (list(layout.decor) if layout is not None else [])
    for item in decor:
        if not item.over:
            draw_decor(canvas, item, _rect(item.box, width, height), scale, owner.path)

    used = 0
    if layout is not None:
        cells = cells_of(output, layout, rng)
        for i, (rect, rotate, look) in enumerate(cells):
            frame = frames[i % len(frames)]
            draw_cell(canvas, frame, rect, rotate, look, scale, owner.path, rng, avoid)
        used = min(len(cells), len(frames))

    draw_layers(canvas, output.overlay, owner.path, scale)
    if layout is not None:
        draw_layers(canvas, layout.overlay, owner.path, scale)
    for item in decor:
        if item.over and not item.above_text:
            draw_decor(canvas, item, _rect(item.box, width, height), scale, owner.path)

    if spec is not None and fitted is not None:
        draw_text(canvas, fitted, spec, area, font_file, scale, owner.path, small)
    for item in decor:
        if item.above_text:
            draw_decor(canvas, item, _rect(item.box, width, height), scale, owner.path)
    return Rendered(image=canvas, frames_used=used, truncated=fitted.truncated if fitted else False)


def _turned(rect: Rect, degrees: float) -> Rect:
    """What a cell turned by `degrees` covers, as an upright box."""
    x, y, w, h = rect
    if not degrees:
        return rect
    turn = math.radians(abs(degrees))
    width = w * math.cos(turn) + h * math.sin(turn)
    tall = w * math.sin(turn) + h * math.cos(turn)
    return (x + (w - width) / 2, y + (h - tall) / 2, width, tall)


def _covered(box: Rect, cells: Sequence[Rect]) -> float:
    """The share of the box under the cells (on a coarse grid)."""
    x, y, w, h = box
    if w <= 0 or h <= 0:
        return 0.0
    steps = 24
    inside = 0
    for i in range(steps):
        for j in range(steps):
            px, py = x + (i + 0.5) * w / steps, y + (j + 0.5) * h / steps
            if any(c[0] <= px <= c[0] + c[2] and c[1] <= py <= c[1] + c[3] for c in cells):
                inside += 1
    return inside / steps**2


def _room_beside(
    cells: Sequence[Rect], alone: Rect, spec: TextBlock, area: Rect, size: float, height: int
) -> float:
    """How high the text with the lines under it may be without reaching the nearest frame in
    the way it grows (down from the top, up from the bottom, both ways from the middle).
    A style that lays the text over its frames (the text alone mostly on them) has no limit; a
    frame the text alone already touches (a wash of colour behind it) is no obstacle."""
    x, top, w, h = alone
    bottom = top + h
    across = [c for c in cells if c[0] < x + w and c[0] + c[2] > x]
    touched = [c for c in across if c[1] < bottom and c[1] + c[3] > top]
    if _covered(alone, touched) > 0.5:
        return area[3]
    across = [c for c in across if c not in touched]
    # Room for the plate, the tape and the pins of a frame too.
    gap = max(size * FRAME_GAP, height * FRAME_GAP_SHARE)
    ceiling = max([area[1], *(c[1] + c[3] for c in across if c[1] + c[3] <= top)]) + gap
    floor = min([area[1] + area[3], *(c[1] for c in across if c[1] >= bottom)]) - gap
    if spec.anchor == "top":
        return floor - area[1]
    if spec.anchor == "bottom":
        return area[1] + area[3] - ceiling
    middle = area[1] + area[3] / 2
    return 2 * min(middle - ceiling, floor - middle)


def _under(
    lines: Sequence[str],
    fitted: FittedText,
    spec: TextBlock,
    area: Rect,
    scale: float,
    measure: Measure,
) -> list[FittedText]:
    """The lines under the text, one line each: a share of the size of the text, not below
    a share of the style's smallest size (unless the text itself is near it), each smaller
    than the one before."""
    result: list[FittedText] = []
    for text, (share, least, most) in zip(lines, UNDER_SIZES, strict=False):
        largest = max(fitted.size * share, min(spec.size[0] * scale * least, fitted.size * most))
        if result:
            largest = min(largest, result[-1].size * 0.85)
        found = fit(text, area[2], largest * 0.6, largest, 1, measure)
        if found.lines:
            result.append(found)
    return result


def _rect(box: tuple[float, float, float, float], width: int, height: int) -> Rect:
    x, y, w, h = box
    return x / 100 * width, y / 100 * height, w / 100 * width, h / 100 * height


def cells_of(
    output: Output, layout: Layout, rng: random.Random | None = None
) -> list[tuple[Rect, float, CellStyle]]:
    """Every cell of the layout in pixels, with its turn and its style, in the frames' order.
    Strewn cells take their shifts from the generator."""
    width, height = output.size
    rng = rng or random.Random(0)
    out: list[tuple[Rect, float, CellStyle]] = []
    for item in layout.cells:
        if isinstance(item, Cell):
            out.append(
                (_rect(item.box, width, height), item.rotate, cell_style(output, layout, item))
            )
            continue
        look = cell_style(output, layout, None)
        if isinstance(item, ScatterItem):
            out += [
                (rect, turn, look) for rect, turn in scatter_rects(item.scatter, width, height, rng)
            ]
        else:
            out += [(rect, item.grid.rotate, look) for rect in grid_rects(item.grid, width, height)]
    return out


def scatter_rects(
    scatter: Scatter, width: int, height: int, rng: random.Random
) -> list[tuple[Rect, float]]:
    out = []
    for k in range(scatter.places):
        x = scatter.xs[k % len(scatter.xs)] + rng.uniform(-scatter.jitter, scatter.jitter)
        y = scatter.ys[k // len(scatter.xs)] + rng.uniform(-scatter.jitter, scatter.jitter)
        turn = rng.uniform(-scatter.turn, scatter.turn)
        out.append((_rect((x, y, scatter.size[0], scatter.size[1]), width, height), turn))
    return out


def grid_rects(grid: Grid, width: int, height: int) -> list[Rect]:
    ax, ay, aw, ah = _rect(grid.area, width, height)
    gap = grid.gap / 100 * width
    xs, ws = _tracks(grid.col_weights, ax, aw, gap)
    ys, hs = _tracks(grid.row_weights, ay, ah, gap)
    spans = grid.spans or [(c, r, 1, 1) for r in range(len(hs)) for c in range(len(ws))]
    return [
        (xs[c], ys[r], sum(ws[c : c + cw]) + gap * (cw - 1), sum(hs[r : r + rh]) + gap * (rh - 1))
        for c, r, cw, rh in spans
    ]


def _tracks(
    weights: list[float], start: float, length: float, gap: float
) -> tuple[list[float], list[float]]:
    free = length - gap * (len(weights) - 1)
    sizes = [free * w / sum(weights) for w in weights]
    starts = []
    at = start
    for size in sizes:
        starts.append(at)
        at += size + gap
    return starts, sizes


def encode(rendered: Rendered, kind: OutputKind) -> bytes:
    """JPEG for pictures with a background, PNG with transparency for the logo."""
    out = io.BytesIO()
    if kind == OutputKind.LOGO:
        rendered.image.save(out, "PNG", compress_level=PNG_COMPRESSION)
    else:
        rendered.image.convert("RGB").save(out, "JPEG", quality=JPEG_QUALITY, optimize=True)
    return out.getvalue()
