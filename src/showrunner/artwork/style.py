# SPDX-License-Identifier: AGPL-3.0-or-later
"""The style: what `style.yaml` may say, and how a style folder is read.

Positions and sizes of boxes are percents of the picture. Lengths (gaps aside, which are
percents of the width) are pixels of the `design` size of an output, so the numbers of a
mock-up can be taken over as they are; the renderer scales them to the real size.

A style may leave out any output but the two posters: the missing ones come from the base
style. Every file a style names must lie inside its folder, as user styles come from a
volume."""

from __future__ import annotations

import enum
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

STYLE_FILE = "style.yaml"
SCHEMA_VERSION = 1

Color = Annotated[str, Field(pattern=r"^#([0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")]
"""#RRGGBB or #RRGGBBAA."""
Percent = Annotated[float, Field(ge=-100, le=200)]
Box = tuple[
    Percent, Percent, Annotated[float, Field(gt=0, le=300)], Annotated[float, Field(gt=0, le=300)]
]
"""x, y, width, height in percents of the picture."""
Point = tuple[Percent, Percent]
Length = Annotated[float, Field(ge=0, le=10000)]
"""Pixels of the design size."""
AssetPath = Annotated[str, Field(min_length=1, max_length=255)]


class StyleError(ValueError):
    """A style folder that can not be used, with the reason."""


class OutputKind(enum.StrEnum):
    SERIES_POSTER = "series_poster"
    SEASON_POSTER = "season_poster"
    LANDSCAPE = "landscape"
    FANART = "fanart"
    LOGO = "logo"


REQUIRED_OUTPUTS = (OutputKind.SERIES_POSTER, OutputKind.SEASON_POSTER)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# --- background -------------------------------------------------------------------------


class Stop(Strict):
    at: Annotated[float, Field(ge=0, le=1)]
    color: Color


class LinearGradient(Strict):
    kind: Literal["linear"]
    angle: float = 180
    """As in CSS: 180 runs from the top down, 90 from left to right."""
    stops: list[Stop] = Field(min_length=2)
    box: Box | None = None
    """Where the gradient lies; the whole picture by default."""


class RadialSpot(Strict):
    """A soft round spot: the color in the middle, fading out to nothing at the radius."""

    kind: Literal["radial"]
    center: Point
    radius: Annotated[float, Field(gt=0, le=300)]
    """Percents of the width."""
    color: Color


class Texture(Strict):
    """A picture over the whole background: cropped to fill it, or repeated as tiles."""

    kind: Literal["texture"]
    image: AssetPath
    opacity: Annotated[float, Field(ge=0, le=1)] = 1
    tile: Length | None = None
    """Width of one tile in design pixels; without it the picture fills the background."""


class Vignette(Strict):
    """Edges darkened towards the corners, the middle left as it is."""

    kind: Literal["vignette"]
    inner: Annotated[float, Field(ge=0, lt=1)] = 0.55
    """Share of the way from the middle to the corner where the darkening starts."""
    color: Color = "#00000073"


BackgroundLayer = Annotated[
    LinearGradient | RadialSpot | Texture | Vignette, Field(discriminator="kind")
]


class Background(Strict):
    color: Color = "#000000"
    layers: list[BackgroundLayer] = []


# --- cells ------------------------------------------------------------------------------


class Shadow(Strict):
    """As a CSS box-shadow: offsets and blur radius in design pixels."""

    dx: float = 0
    dy: float = 2
    blur: Length = 8
    color: Color = "#00000080"


class Border(Strict):
    width: Length
    color: Color


class Mat(Strict):
    """A margin of plain color around the frame inside the cell, like a print's white border."""

    color: Color = "#FFFFFF"
    top: Length = 0
    right: Length = 0
    bottom: Length = 0
    left: Length = 0


class Filter(Strict):
    brightness: Annotated[float, Field(ge=0, le=3)] = 1
    saturation: Annotated[float, Field(ge=0, le=3)] = 1
    contrast: Annotated[float, Field(ge=0, le=3)] = 1
    blur: Length = 0
    grayscale: bool = False


class Attachment(Strict):
    """A picture stuck to a cell — tape, a pin, a clip — turned a little at random."""

    image: AssetPath
    width: Annotated[float, Field(gt=0, le=200)]
    """Percents of the cell width."""
    anchor: Literal["top", "bottom", "top_left", "top_right"] = "top"
    dy: Annotated[float, Field(ge=-100, le=100)] = 0
    """Shift down, in percents of the cell height."""
    turn: Annotated[float, Field(ge=-180, le=180)] = 0
    jitter: Annotated[float, Field(ge=0, le=45)] = 0
    """Up to this many degrees either way, from the seed."""


class CellStyle(Strict):
    shape: Literal["rect", "circle", "diamond", "polygon", "mask"] = "rect"
    points: list[Point] | None = None
    """For a polygon: corners in percents of the cell."""
    mask: AssetPath | None = None
    """For a mask: a picture whose alpha (or, without alpha, brightness) is the shape."""
    radius: Length = 0
    border: Border | None = None
    mat: Mat | None = None
    shadow: Shadow | None = None
    filter: Filter | None = None
    attachments: list[Attachment] = []

    @model_validator(mode="after")
    def _shape_needs(self) -> CellStyle:
        if self.shape == "polygon" and (not self.points or len(self.points) < 3):
            raise ValueError("a polygon needs at least three points")
        if self.shape == "mask" and not self.mask:
            raise ValueError("a mask shape needs a mask picture")
        return self


class Cell(Strict):
    box: Box
    rotate: Annotated[float, Field(ge=-180, le=180)] = 0
    style: dict[str, Any] | None = None
    """Fields of the cell style that differ for this cell."""


class Grid(Strict):
    """Cells on a grid. Columns and rows are a count of equal ones or a list of their weights;
    without spans every place of the grid is a cell, row by row."""

    area: Box = (0, 0, 100, 100)
    cols: Annotated[int, Field(ge=1, le=12)] | list[Annotated[float, Field(gt=0)]]
    rows: Annotated[int, Field(ge=1, le=12)] | list[Annotated[float, Field(gt=0)]]
    gap: Annotated[float, Field(ge=0, le=20)] = 0
    """Percents of the width; the same number of pixels between rows."""
    spans: list[tuple[int, int, int, int]] | None = None
    """Merged cells: column, row, width, height in places of the grid."""
    rotate: Annotated[float, Field(ge=-180, le=180)] = 0

    @property
    def col_weights(self) -> list[float]:
        return [1.0] * self.cols if isinstance(self.cols, int) else list(self.cols)

    @property
    def row_weights(self) -> list[float]:
        return [1.0] * self.rows if isinstance(self.rows, int) else list(self.rows)

    @property
    def count(self) -> int:
        return (
            len(self.spans)
            if self.spans is not None
            else len(self.col_weights) * len(self.row_weights)
        )

    @model_validator(mode="after")
    def _spans_fit(self) -> Grid:
        cols, rows = len(self.col_weights), len(self.row_weights)
        for col, row, width, height in self.spans or []:
            if (
                col < 0
                or row < 0
                or width < 1
                or height < 1
                or col + width > cols
                or row + height > rows
            ):
                raise ValueError(
                    f"span {[col, row, width, height]} is outside a {cols} by {rows} grid"
                )
        return self


class GridItem(Strict):
    grid: Grid


class Scatter(Strict):
    """Cells of one size strewn over places, row by row, each shifted and turned a little at
    random (from the seed), like prints thrown on a table."""

    xs: list[Percent] = Field(min_length=1)
    ys: list[Percent] = Field(min_length=1)
    size: tuple[Annotated[float, Field(gt=0, le=200)], Annotated[float, Field(gt=0, le=200)]]
    """Width and height in percents of the picture."""
    jitter: Annotated[float, Field(ge=0, le=20)] = 0
    """Up to this many percents either way."""
    turn: Annotated[float, Field(ge=0, le=45)] = 0
    """Up to this many degrees either way."""
    count: Annotated[int, Field(ge=1, le=24)] | None = None
    """Fewer cells than places; all places by default."""

    @property
    def places(self) -> int:
        return self.count or len(self.xs) * len(self.ys)

    @model_validator(mode="after")
    def _count_fits(self) -> Scatter:
        if self.places > len(self.xs) * len(self.ys):
            raise ValueError("more cells than places")
        return self


class ScatterItem(Strict):
    scatter: Scatter


class Decor(Strict):
    """A fixed picture or a plain colored box, under the frames or over them. A picture is
    stretched to the box or repeated along it as tiles."""

    image: AssetPath | None = None
    color: Color | None = None
    box: Box
    rotate: Annotated[float, Field(ge=-180, le=180)] = 0
    over: bool = False
    above_text: bool = False
    """Over the text as well (a pin through a note)."""
    tile: tuple[Length, Length] | None = None
    """Size of one tile in design pixels."""
    radius: Length = 0
    shadow: Shadow | None = None

    @model_validator(mode="after")
    def _one_fill(self) -> Decor:
        if (self.image is None) == (self.color is None):
            raise ValueError("decor needs either an image or a color")
        return self


class Layout(Strict):
    """The cells for one number of frames. Frames go to cells in order, the best one first."""

    cells: list[Cell | GridItem | ScatterItem] = Field(min_length=1)
    cell: dict[str, Any] | None = None
    """Fields of the cell style that differ for this layout."""
    decor: list[Decor] = []
    """Decor of this layout only, drawn after the output's."""
    text: dict[str, Any] | None = None
    """Fields of the output's text that differ for this layout (where the title stands)."""
    overlay: list[BackgroundLayer] = []
    """Layers over the frames of this layout only, after the output's."""

    @property
    def frames(self) -> int:
        total = 0
        for item in self.cells:
            if isinstance(item, GridItem):
                total += item.grid.count
            elif isinstance(item, ScatterItem):
                total += item.scatter.places
            else:
                total += 1
        return total


# --- text -------------------------------------------------------------------------------


class Stroke(Strict):
    width: Length
    color: Color


class Plate(Strict):
    """What lies under the text so it can be read on a picture; it grows with the text.

    fade: the whole width, from the top of the text (less `pad_top`) down to the bottom
    edge, solid and then fading out over `fade` pixels above.
    band: the whole width, around the text only.
    box: around the text lines only."""

    kind: Literal["fade", "band", "box"]
    color: Color = "#08090CE6"
    fade: Length = 0
    fade_from: Annotated[float, Field(ge=0, le=1)] = 0.9
    """Share of the color's alpha where the fading starts."""
    pad_top: Length = 0
    pad_x: Length = 0
    pad_bottom: Length = 0
    radius: Length = 0
    across: tuple[Percent, Annotated[float, Field(gt=0, le=200)]] | None = None
    """Left edge and width of a fade or band in percents; the whole width by default."""
    to_edge: bool | None = None
    """The plate reaches down to the bottom edge; otherwise it ends under the text. By default
    a fade does and a band does not."""
    image: AssetPath | None = None
    """A picture repeated over the plate (paper, grid lines)."""
    tile: Length = 24
    """Width of one tile of the image, in design pixels."""
    mask: AssetPath | None = None
    """A picture stretched over a box plate whose alpha cuts its shape (a torn edge)."""
    shadow: Shadow | None = None


class TextBlock(Strict):
    font: str
    color: Color = "#FFFFFF"
    area: Box
    """Where the lines go: their width is the area's width."""
    anchor: Literal["top", "center", "bottom"] = "bottom"
    align: Literal["left", "center", "right"] = "left"
    size: tuple[Annotated[float, Field(gt=0, le=1000)], Annotated[float, Field(gt=0, le=1000)]]
    """Smallest and largest size."""
    max_lines: Annotated[int, Field(ge=1, le=6)] = 2
    line_height: Annotated[float, Field(gt=0.5, le=3)] = 1.1
    uppercase: bool = False
    letter_spacing: Annotated[float, Field(ge=-0.2, le=1)] = 0
    """Extra space between letters, in parts of the size (CSS em)."""
    rotate: Annotated[float, Field(ge=-45, le=45)] = 0
    """The text with its plate turned around its middle."""
    shadow: Shadow | None = None
    stroke: Stroke | None = None
    plate: Plate | None = None

    @model_validator(mode="after")
    def _sizes(self) -> TextBlock:
        if self.size[0] > self.size[1]:
            raise ValueError("the smallest size is larger than the largest")
        return self


# --- outputs and the style ---------------------------------------------------------------


class Output(Strict):
    size: tuple[Annotated[int, Field(ge=16, le=4096)], Annotated[int, Field(ge=16, le=4096)]]
    design: tuple[Annotated[float, Field(gt=0)], Annotated[float, Field(gt=0)]] | None = None
    """The size the lengths are given for; the real size if left out."""
    background: Background | None = None
    """None leaves the picture transparent (a logo)."""
    cell: CellStyle = CellStyle()
    layouts: list[Layout] = []
    decor: list[Decor] = []
    overlay: list[BackgroundLayer] = []
    """Layers over the frames and under the text: a darkening, a vignette."""
    text: TextBlock | None = None

    @property
    def scale(self) -> float:
        return self.size[0] / self.design[0] if self.design else 1.0

    @model_validator(mode="after")
    def _layouts(self) -> Output:
        counts = [layout.frames for layout in self.layouts]
        if len(set(counts)) != len(counts):
            raise ValueError(f"two layouts for the same number of frames: {sorted(counts)}")
        if (
            self.design
            and abs(self.design[0] / self.design[1] - self.size[0] / self.size[1]) > 0.01
        ):
            raise ValueError("design and size have different proportions")
        return self

    def layout_for(self, frames: int) -> Layout | None:
        """The layout with the most cells that the frames can fill."""
        fitting = [layout for layout in self.layouts if layout.frames <= frames]
        if fitting:
            return max(fitting, key=lambda layout: layout.frames)
        return min(self.layouts, key=lambda layout: layout.frames) if self.layouts else None


class FontRef(Strict):
    file: AssetPath
    index: Annotated[int, Field(ge=0)] = 0
    variation: str | None = None
    """A named instance of a variable font, such as "Bold"."""


class StyleSpec(Strict):
    """The content of `style.yaml`."""

    schema_version: Literal[1] = Field(alias="schema")
    id: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,47}$")]
    version: Annotated[int, Field(ge=1)]
    """Raised on every change of the look, so the pictures are made again."""
    names: dict[str, str] = {}
    """The name in each language of the interface."""
    max_frames: Annotated[int, Field(ge=1, le=24)]
    fonts: dict[str, FontRef] = {}
    outputs: dict[OutputKind, Output]

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    @model_validator(mode="after")
    def _fonts_known(self) -> StyleSpec:
        for kind, output in self.outputs.items():
            if output.text and output.text.font not in self.fonts:
                raise ValueError(f"{kind}: the font {output.text.font!r} is not among the fonts")
        return self


def json_schema() -> dict[str, Any]:
    """The JSON Schema of `style.yaml`, for editors and for the documentation."""
    return StyleSpec.model_json_schema(by_alias=True)


@dataclass(frozen=True)
class Style:
    """A read style folder. `base` gives the outputs this style leaves out."""

    spec: StyleSpec
    root: Path
    base: Style | None = None

    @property
    def id(self) -> str:
        return self.spec.id

    def output(self, kind: OutputKind) -> tuple[Output, Style]:
        """The output and the style it comes from (its fonts and assets are used with it)."""
        if kind in self.spec.outputs:
            return self.spec.outputs[kind], self
        if self.base is not None:
            return self.base.output(kind)
        raise StyleError(f"style {self.id!r} has no {kind} and no base style to take it from")

    def path(self, relative: str) -> Path:
        return _inside(self.root, relative)

    def font_path(self, name: str) -> FontFile:
        font = self.spec.fonts[name]
        return FontFile(self.path(font.file), font.index, font.variation)


@dataclass(frozen=True)
class FontFile:
    path: Path
    index: int = 0
    variation: str | None = None


def _inside(root: Path, relative: str) -> Path:
    """The file of a style, refusing anything that leads out of its folder."""
    pure = PurePosixPath(relative.replace("\\", "/"))
    if pure.is_absolute() or ".." in pure.parts or ":" in relative:
        raise StyleError(f"{relative!r} must be a path inside the style folder")
    path = (root / Path(*pure.parts)).resolve()
    if not path.is_relative_to(root.resolve()):
        raise StyleError(f"{relative!r} leads out of the style folder")
    if not path.is_file():
        raise StyleError(f"{relative!r} is not in the style folder")
    return path


def _named_files(spec: StyleSpec) -> list[str]:
    files = [font.file for font in spec.fonts.values()]
    for output in spec.outputs.values():
        layers = list(output.overlay)
        if output.background:
            layers += output.background.layers
        files += [layer.image for layer in layers if isinstance(layer, Texture)]
        decor = list(output.decor)
        styles = [output.cell.model_dump(exclude_none=True)]
        for layout in output.layouts:
            decor += layout.decor
            styles.append(layout.cell or {})
            styles += [item.style or {} for item in layout.cells if isinstance(item, Cell)]
        files += [item.image for item in decor if item.image]
        for style in styles:
            if style.get("mask"):
                files.append(style["mask"])
            files += [attachment["image"] for attachment in style.get("attachments", [])]
        if output.text and output.text.plate:
            plate = output.text.plate
            files += [name for name in (plate.image, plate.mask) if name]
    return files


def load_style(folder: Path, base: Style | None = None) -> Style:
    """Read and check a style folder. Raises StyleError with the reason."""
    file = folder / STYLE_FILE
    try:
        raw = yaml.safe_load(file.read_text(encoding="utf-8"))
    except OSError as exc:
        raise StyleError(f"{file}: can not be read: {exc}") from exc
    except yaml.YAMLError as exc:
        raise StyleError(f"{file}: not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise StyleError(f"{file}: must be a mapping")
    if raw.get("schema") != SCHEMA_VERSION:
        raise StyleError(
            f"{file}: schema {raw.get('schema')!r} is not supported (expected {SCHEMA_VERSION})"
        )
    try:
        spec = StyleSpec.model_validate(raw)
    except ValidationError as exc:
        raise StyleError(f"{file}: {exc}") from exc
    missing = [kind.value for kind in REQUIRED_OUTPUTS if kind not in spec.outputs]
    if missing:
        raise StyleError(f"{file}: a style must have {', '.join(missing)}")
    for output in spec.outputs.values():
        for layout in output.layouts:
            for item in layout.cells:
                if isinstance(item, Cell) and item.style:
                    _cell_style(output.cell, layout.cell, item.style, where=str(file))
            if layout.cell:
                _cell_style(output.cell, layout.cell, None, where=str(file))
    root = folder.resolve()
    for relative in _named_files(spec):
        _inside(root, relative)
    return Style(spec=spec, root=root, base=base)


def _cell_style(
    base: CellStyle, layout: dict[str, Any] | None, cell: dict[str, Any] | None, where: str = ""
) -> CellStyle:
    """The style of one cell: the output's, then the layout's fields, then the cell's."""
    merged = base.model_dump(exclude_unset=True)
    merged.update(layout or {})
    merged.update(cell or {})
    try:
        return CellStyle.model_validate(merged)
    except ValidationError as exc:
        raise StyleError(f"{where}: cell style: {exc}") from exc


def text_block(output: Output, layout: Layout | None) -> TextBlock | None:
    """The output's text with the layout's changes."""
    if output.text is None or layout is None or not layout.text:
        return output.text
    merged = output.text.model_dump(exclude_unset=True)
    merged.update(layout.text)
    return TextBlock.model_validate(merged)


def cell_style(output: Output, layout: Layout, cell: Cell | None) -> CellStyle:
    return _cell_style(output.cell, layout.cell, cell.style if cell else None)


BUILTIN_STYLES = Path(__file__).parent / "styles"
BASE_STYLE = "mosaic"


def builtin_styles() -> dict[str, Style]:
    """The styles shipped with the app; every one falls back on the base style."""
    base = load_style(BUILTIN_STYLES / BASE_STYLE)
    styles = {base.id: base}
    for folder in sorted(BUILTIN_STYLES.iterdir()):
        if folder.name != BASE_STYLE and (folder / STYLE_FILE).is_file():
            style = load_style(folder, base=base)
            styles[style.id] = style
    return styles
