# SPDX-License-Identifier: AGPL-3.0-or-later
"""One picture of a style: the background, fixed pictures under the frames, the frames in
the cells of the layout, fixed pictures over them, and the text on its plate.

The layout is the one with the most cells the frames can fill, up to the style's limit;
frames go to cells in the given order, so the best frame should come first. The jitter of
attachments comes from the seed: the same style, frames, text and seed give the same bytes."""

from __future__ import annotations

import io
import random
from collections.abc import Sequence
from dataclasses import dataclass

from PIL import Image

from showrunner.artwork.paint import (
    Frame,
    Rect,
    background,
    draw_cell,
    draw_decor,
    draw_layers,
    draw_text,
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
    cell_style,
    text_block,
)
from showrunner.artwork.text import fit, font_measure

JPEG_QUALITY = 90
PNG_COMPRESSION = 9


@dataclass(frozen=True)
class Rendered:
    image: Image.Image
    frames_used: int
    truncated: bool
    """The text did not fit at the smallest size and was cut with "…"."""


def render(
    style: Style, kind: OutputKind, frames: Sequence[Frame], text: str, seed: int
) -> Rendered:
    output, owner = style.output(kind)
    width, height = output.size
    scale = output.scale
    rng = random.Random(f"{style.id}/{style.spec.version}/{kind}/{seed}")
    if output.background is not None:
        canvas = background(output.size, output.background, owner.path, scale)
    else:
        canvas = Image.new("RGBA", output.size, (0, 0, 0, 0))

    layout = output.layout_for(min(len(frames), style.spec.max_frames)) if frames else None
    decor = list(output.decor) + (list(layout.decor) if layout is not None else [])
    for item in decor:
        if not item.over:
            draw_decor(canvas, item, _rect(item.box, width, height), scale, owner.path)

    used = 0
    if layout is not None:
        cells = cells_of(output, layout, rng)
        for i, (rect, rotate, look) in enumerate(cells):
            draw_cell(canvas, frames[i % len(frames)], rect, rotate, look, scale, owner.path, rng)
        used = min(len(cells), len(frames))

    draw_layers(canvas, output.overlay, owner.path, scale)
    for item in decor:
        if item.over and not item.above_text:
            draw_decor(canvas, item, _rect(item.box, width, height), scale, owner.path)

    truncated = False
    spec = text_block(output, layout)
    if spec is not None and text.strip():
        font_file = owner.font_path(spec.font)
        area = _rect(spec.area, width, height)
        content = text.upper() if spec.uppercase else text
        measure = font_measure(
            font_file.path, font_file.index, font_file.variation, spec.letter_spacing
        )
        fitted = fit(
            content,
            area[2],
            spec.size[0] * scale,
            spec.size[1] * scale,
            spec.max_lines,
            measure,
            height=area[3],
            line_height=spec.line_height,
        )
        truncated = fitted.truncated
        draw_text(canvas, fitted, spec, area, font_file, scale, owner.path)
    for item in decor:
        if item.above_text:
            draw_decor(canvas, item, _rect(item.box, width, height), scale, owner.path)
    return Rendered(image=canvas, frames_used=used, truncated=truncated)


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
