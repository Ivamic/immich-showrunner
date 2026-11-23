# SPDX-License-Identifier: AGPL-3.0-or-later
"""Artwork: styles are checked when read, titles fit their box, pictures are drawn the same
every time. Frames here are synthetic."""

import io
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from showrunner.artwork.paint import (
    Frame,
    cover,
    free_space,
    linear_gradient,
    radial_spot,
    shape_mask,
    vignette,
    visible_part,
)
from showrunner.artwork.render import encode, grid_rects, render
from showrunner.artwork.style import (
    BUILTIN_STYLES,
    Grid,
    LinearGradient,
    OutputKind,
    RadialSpot,
    Stop,
    Style,
    StyleError,
    Vignette,
    builtin_styles,
    json_schema,
    load_style,
    text_block,
)
from showrunner.artwork.text import ELLIPSIS, fit, font_measure

MONTSERRAT = BUILTIN_STYLES / "mosaic" / "fonts" / "Montserrat-ExtraBold.ttf"
TITLES = {
    "short": "Winter",
    "medium": "Summer by the sea",
    "long": "Holidays at grandma's in the village",
    "very_long": "A trip with the whole family to grandma and grandpa in the village "
    "for the summer holidays, fishing and haymaking",
    "file_name": "VID_20190714_holidays_at_grandmas_final_v2",
}
FRAME_COUNTS = (1, 3, 6, 12)


def synthetic_frame(i: int, size: tuple[int, int] = (640, 360)) -> Frame:
    """A frame with a colored background, a few shapes and a number, different for each i."""
    image = Image.new("RGB", size, ((i * 53) % 256, (i * 97) % 256, (i * 151) % 256))
    draw = ImageDraw.Draw(image)
    w, h = size
    draw.ellipse((w * 0.3, h * 0.2, w * 0.6, h * 0.8), fill=(255 - (i * 53) % 256, 200, 80))
    draw.rectangle((w * 0.65, h * 0.1, w * 0.9, h * 0.5), fill=(30, 30, 30))
    draw.text((10, 10), str(i), fill=(255, 255, 255))
    return Frame(image=image, focus=(0.45, 0.5))


FRAMES = [synthetic_frame(i, (640, 360) if i % 3 else (360, 640)) for i in range(12)]


@pytest.fixture(scope="module")
def styles() -> dict[str, Style]:
    return builtin_styles()


# --- text -------------------------------------------------------------------------------

MEASURE = font_measure(MONTSERRAT)


@pytest.mark.parametrize("key", list(TITLES))
def test_title_fits_the_width(key: str) -> None:
    fitted = fit(TITLES[key].upper(), 600, 40, 90, 3, MEASURE)
    assert 1 <= len(fitted.lines) <= 3
    assert 40 <= fitted.size <= 90
    for line in fitted.lines:
        assert MEASURE(line, fitted.size) <= 600


def test_short_title_takes_one_line_at_the_largest_size() -> None:
    fitted = fit("WINTER", 600, 40, 90, 3, MEASURE)
    assert fitted == fit("  WINTER ", 600, 40, 90, 3, MEASURE)
    assert fitted.lines == ("WINTER",) and fitted.size == 90 and not fitted.truncated


def test_too_long_title_is_cut_at_a_word() -> None:
    fitted = fit(TITLES["very_long"], 600, 40, 90, 2, MEASURE)
    assert fitted.truncated and fitted.size == 40 and len(fitted.lines) == 2
    last = fitted.lines[-1]
    assert last.endswith(ELLIPSIS)
    kept = last.removesuffix(ELLIPSIS)
    assert kept == kept.rstrip(" ,.;:-_")
    assert len(kept.split()[-1]) > 2, "no short word left hanging before the ellipsis"
    assert all(word in TITLES["very_long"] for word in kept.split())


def test_short_word_stays_with_the_next_one() -> None:
    fitted = fit("Summer at the lake in a small village", 500, 30, 90, 3, MEASURE)
    for line in fitted.lines[:-1]:
        assert len(line.split()[-1]) > 2, fitted.lines


def test_file_name_breaks_after_underscores() -> None:
    fitted = fit(TITLES["file_name"], 500, 40, 90, 3, MEASURE)
    assert all(MEASURE(line, fitted.size) <= 500 for line in fitted.lines)
    assert "".join(fitted.lines).replace(ELLIPSIS, "") in TITLES["file_name"]
    assert all(line.endswith("_") for line in fitted.lines[:-1])


def test_a_dash_between_words_keeps_its_spaces_and_ends_a_line() -> None:
    title = "2026-06_07 - Dubrovnik - Rome - Tivoli"
    for width in (400, 600, 900, 2000):
        fitted = fit(title, width, 20, 90, 3, MEASURE)
        assert " ".join(fitted.lines) == title, fitted.lines
        assert not any(line.startswith("-") for line in fitted.lines[1:]), fitted.lines


def test_a_date_in_a_title_stays_whole_while_it_fits() -> None:
    for width in (300, 500, 800):
        fitted = fit("2017-03-27_30 - Moscow", width, 30, 90, 3, MEASURE)
        assert any("2017-03-27_30" in line for line in fitted.lines), fitted.lines
    en = "\N{EN DASH}"
    assert fit(f"Rome {en} Tivoli", 2000, 20, 90, 1, MEASURE).lines == (f"Rome {en} Tivoli",)


def test_word_wider_than_the_line_breaks_between_letters() -> None:
    word = "Supercalifragilisticexpialidocious"
    fitted = fit(word, 300, 40, 90, 4, MEASURE)
    assert all(MEASURE(line, fitted.size) <= 300 for line in fitted.lines)
    assert fitted.lines[0].endswith("-")
    assert "".join(line.removesuffix("-") for line in fitted.lines) == word


def test_empty_title_has_no_lines() -> None:
    assert fit("  ", 600, 40, 90, 2, MEASURE).lines == ()


# --- the base style ---------------------------------------------------------------------


BUILTIN = [
    "mosaic",
    "polaroid",
    "film",
    "afisha",
    "watercolor",
    "board",
    "diamonds",
    "diagonal",
    "editorial",
]
LANGUAGES = {"en", "de", "fr", "it", "ru"}


def test_builtin_styles_load(styles: dict[str, Style]) -> None:
    assert sorted(styles) == sorted(BUILTIN)
    mosaic = styles["mosaic"]
    assert set(mosaic.spec.outputs) == set(OutputKind)
    assert mosaic.spec.names["ru"] == "Мозаика"
    for style in styles.values():
        assert set(style.spec.names) == LANGUAGES, style.id
        assert style.id == "mosaic" or style.base is mosaic
    assert "properties" in json_schema()


@pytest.mark.parametrize("kind", list(OutputKind))
@pytest.mark.parametrize("name", BUILTIN)
def test_every_style_every_output_every_frame_count(
    styles: dict[str, Style], name: str, kind: OutputKind
) -> None:
    style = styles[name]
    output, _ = style.output(kind)
    for count in FRAME_COUNTS:
        titles = TITLES.items() if count == 6 else [("long", TITLES["long"])]
        for key, title in titles:
            rendered = render(style, kind, FRAMES[:count], title, seed=7)
            assert rendered.image.size == output.size, (count, key)
            if output.layouts:
                assert 1 <= rendered.frames_used <= min(count, style.spec.max_frames)
            picture = Image.open(io.BytesIO(encode(rendered, kind)))
            assert picture.size == output.size
            assert picture.format == ("PNG" if kind == OutputKind.LOGO else "JPEG")


def test_layout_uses_as_many_frames_as_it_can(styles: dict[str, Style]) -> None:
    mosaic = styles["mosaic"]
    used = {
        n: render(mosaic, OutputKind.SERIES_POSTER, FRAMES[:n], "", 1).frames_used
        for n in range(1, 13)
    }
    assert used == {1: 1, 2: 1, 3: 3, 4: 3, 5: 3, 6: 6, 7: 6, 8: 6, 9: 6, 10: 6, 11: 6, 12: 12}


@pytest.mark.parametrize("name", BUILTIN)
def test_same_input_gives_the_same_bytes(styles: dict[str, Style], name: str) -> None:
    for kind in OutputKind:
        first = encode(render(styles[name], kind, FRAMES[:6], TITLES["long"], seed=3), kind)
        again = encode(render(styles[name], kind, FRAMES[:6], TITLES["long"], seed=3), kind)
        assert first == again, kind


def test_strewn_prints_move_with_the_seed(styles: dict[str, Style]) -> None:
    """Polaroid scatters six prints: another seed, another arrangement; same seed, same one."""
    kind = OutputKind.SERIES_POSTER
    one = encode(render(styles["polaroid"], kind, FRAMES[:6], "", seed=1), kind)
    again = encode(render(styles["polaroid"], kind, FRAMES[:6], "", seed=1), kind)
    other = encode(render(styles["polaroid"], kind, FRAMES[:6], "", seed=2), kind)
    assert one == again != other


def test_layout_moves_the_title(styles: dict[str, Style]) -> None:
    """Playbill puts the title on the lower edge of the main frame, which is higher with more
    frames below it."""
    afisha = styles["afisha"]
    output, _ = afisha.output(OutputKind.SERIES_POSTER)
    one = text_block(output, output.layout_for(1))
    six = text_block(output, output.layout_for(6))
    assert one is not None and six is not None
    assert one.area[3] > six.area[3]
    assert one.plate is not None and one.plate.to_edge is None
    assert six.plate is not None and six.plate.to_edge is False


def test_logo_is_transparent_around_the_title(styles: dict[str, Style]) -> None:
    logo = render(styles["mosaic"], OutputKind.LOGO, [], "Winter", seed=1).image
    assert logo.mode == "RGBA"
    assert logo.getpixel((0, 0))[3] == 0  # type: ignore[index]
    assert logo.getchannel("A").getextrema()[1] == 255


def test_text_lies_on_a_plate(styles: dict[str, Style]) -> None:
    """The bottom of a poster with a title is darker than without one: the plate is there."""
    white = [Frame(Image.new("RGB", (400, 600), (255, 255, 255)))]
    plain = render(styles["mosaic"], OutputKind.SERIES_POSTER, white, "", 1).image
    titled = render(styles["mosaic"], OutputKind.SERIES_POSTER, white, "Winter", 1).image
    assert plain.getpixel((20, 1490))[0] == 255  # type: ignore[index]
    assert titled.getpixel((20, 1490))[0] < 60  # type: ignore[index]
    assert titled.getpixel((20, 100))[0] == 255  # type: ignore[index]


# --- geometry ---------------------------------------------------------------------------


def test_cover_keeps_the_focus_point_in_view() -> None:
    image = Image.new("RGB", (400, 100), (0, 0, 255))
    image.paste((255, 0, 0), (0, 0, 100, 100))
    left = cover(image, (100, 100), (0.0, 0.5))
    right = cover(image, (100, 100), (1.0, 0.5))
    assert left.getpixel((50, 50))[:3] == (255, 0, 0)  # type: ignore[index]
    assert right.getpixel((50, 50))[:3] == (0, 0, 255)  # type: ignore[index]


def test_grid_cells_have_equal_gaps_in_pixels() -> None:
    grid = Grid(cols=2, rows=[58, 42], gap=1, spans=[(0, 0, 2, 1), (0, 1, 1, 1), (1, 1, 1, 1)])
    top, bottom_left, bottom_right = grid_rects(grid, 1000, 1500)
    assert top == pytest.approx((0, 0, 1000, (1500 - 10) * 0.58))
    assert bottom_left[1] - (top[1] + top[3]) == pytest.approx(10)
    assert bottom_right[0] - (bottom_left[0] + bottom_left[2]) == pytest.approx(10)
    assert bottom_right[0] + bottom_right[2] == pytest.approx(1000)
    assert bottom_left[1] + bottom_left[3] == pytest.approx(1500)


# --- user styles ------------------------------------------------------------------------

MINIMAL = """
schema: 1
id: test
version: 1
max_frames: 6
fonts: {title: {file: fonts/title.ttf}}
outputs:
  series_poster: &poster
    size: [200, 300]
    background: {color: "#202020"}
    layouts: [{cells: [{box: [0, 0, 100, 100]}]}]
    text: {font: title, area: [5, 5, 90, 90], size: [10, 30]}
  season_poster: *poster
"""


def make_style(folder: Path, text: str = MINIMAL) -> Path:
    (folder / "fonts").mkdir(parents=True, exist_ok=True)
    (folder / "fonts" / "title.ttf").write_bytes(MONTSERRAT.read_bytes())
    (folder / "style.yaml").write_text(text, encoding="utf-8")
    return folder


def test_missing_outputs_come_from_the_base_style(tmp_path: Path, styles: dict[str, Style]) -> None:
    style = load_style(make_style(tmp_path), base=styles["mosaic"])
    output, owner = style.output(OutputKind.FANART)
    assert owner.id == "mosaic"
    assert render(style, OutputKind.FANART, FRAMES[:3], "", 1).image.size == output.size
    with pytest.raises(StyleError, match="no fanart"):
        load_style(tmp_path).output(OutputKind.FANART)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (("fonts/title.ttf", "../title.ttf"), "inside the style folder"),
        (("fonts/title.ttf", "/etc/passwd"), "inside the style folder"),
        (("fonts/title.ttf", "C:/fonts/title.ttf"), "inside the style folder"),
        (("fonts/title.ttf", "fonts/missing.ttf"), "not in the style folder"),
        (("schema: 1", "schema: 2"), "schema 2 is not supported"),
        (("max_frames: 6", "max_frames: 6\nscript: run.py"), "Extra inputs"),
        (("font: title", "font: other"), "not among the fonts"),
        (("  season_poster: *poster\n", ""), "must have season_poster"),
        (("[0, 0, 100, 100]", "[0, 0, 0, 100]"), "greater than 0"),
        (('color: "#202020"', "color: red"), "should match pattern"),
    ],
)
def test_bad_style_is_refused(tmp_path: Path, change: tuple[str, str], message: str) -> None:
    make_style(tmp_path, MINIMAL.replace(*change))
    with pytest.raises(StyleError, match=message):
        load_style(tmp_path)


def test_grid_span_outside_the_grid_is_refused(tmp_path: Path) -> None:
    text = MINIMAL.replace(
        "{cells: [{box: [0, 0, 100, 100]}]}",
        "{cells: [{grid: {cols: 2, rows: 2, spans: [[1, 1, 2, 1]]}}]}",
    )
    make_style(tmp_path, text)
    with pytest.raises(StyleError, match="outside a 2 by 2 grid"):
        load_style(tmp_path)


EVERYTHING = """
schema: 1
id: everything
version: 3
max_frames: 6
fonts: {title: {file: fonts/title.ttf}}
outputs:
  series_poster:
    size: [300, 450]
    design: [360, 540]
    background:
      color: "#E9DFCC"
      layers:
        - kind: linear
          angle: 135
          stops: [{at: 0, color: "#FFFFFF80"}, {at: 1, color: "#00000040"}]
        - {kind: radial, center: [20, 20], radius: 40, color: "#FF000080"}
        - {kind: texture, image: assets/paper.png, opacity: 0.3}
    decor: [{image: assets/tape.png, box: [40, 2, 20, 6], rotate: 10}]
    cell:
      mat: {color: "#FFFFFF", top: 8, right: 8, bottom: 30, left: 8}
      shadow: {dx: 2, dy: 4, blur: 6, color: "#00000066"}
      attachments: [{image: assets/tape.png, width: 40, jitter: 8}]
    layouts:
      - cells: [{box: [10, 10, 80, 60], rotate: -3}]
      - cells:
          - {box: [5, 5, 40, 30], rotate: 4, style: {shape: circle}}
          - {box: [55, 5, 40, 30], style: {shape: diamond, filter: {grayscale: true, blur: 2}}}
          - box: [5, 40, 40, 30]
            style: {shape: polygon, points: [[0, 0], [100, 10], [90, 100], [0, 90]]}
          - box: [55, 40, 40, 30]
            style: {shape: mask, mask: assets/mask.png, border: {width: 2, color: "#FF0000"}}
          - grid: {area: [5, 72, 90, 18], cols: 2, rows: 1, gap: 2, rotate: 2}
    text:
      font: title
      color: "#3B2F27"
      area: [10, 80, 80, 15]
      anchor: center
      align: center
      size: [14, 40]
      plate: {kind: box, color: "#FFFFFFDD", pad_x: 10, pad_top: 4, pad_bottom: 4, radius: 6}
  season_poster:
    size: [300, 450]
    design: [360, 540]
    layouts: [{cells: [{grid: {cols: 2, rows: 2, gap: 1}}]}]
    text: {font: title, area: [0, 40, 100, 20], anchor: center, align: right, size: [60, 60],
           stroke: {width: 2, color: "#000000"},
           plate: {kind: band, color: "#00000080", pad_top: 6, pad_bottom: 6}}
"""


@pytest.fixture
def everything(tmp_path: Path) -> Style:
    folder = make_style(tmp_path, EVERYTHING)
    (folder / "assets").mkdir()
    Image.new("RGBA", (64, 20), (240, 230, 200, 200)).save(folder / "assets" / "tape.png")
    Image.new("RGB", (32, 32), (180, 170, 150)).save(folder / "assets" / "paper.png")
    mask = Image.new("RGBA", (50, 50), (0, 0, 0, 0))
    ImageDraw.Draw(mask).ellipse((5, 5, 45, 45), fill=(255, 255, 255, 255))
    mask.save(folder / "assets" / "mask.png")
    return load_style(folder)


def test_every_primitive_draws(everything: Style) -> None:
    for count in (1, 6):
        for kind in (OutputKind.SERIES_POSTER, OutputKind.SEASON_POSTER):
            rendered = render(everything, kind, FRAMES[:count], TITLES["long"], seed=1)
            assert rendered.image.size == (300, 450)
    first = encode(
        render(everything, OutputKind.SERIES_POSTER, FRAMES[:6], "Title", seed=1),
        OutputKind.SERIES_POSTER,
    )
    again = encode(
        render(everything, OutputKind.SERIES_POSTER, FRAMES[:6], "Title", seed=1),
        OutputKind.SERIES_POSTER,
    )
    other = encode(
        render(everything, OutputKind.SERIES_POSTER, FRAMES[:6], "Title", seed=2),
        OutputKind.SERIES_POSTER,
    )
    assert first == again
    assert first != other, "the seed turns the attachments"


def test_mask_and_attachments_must_be_inside_the_folder(tmp_path: Path) -> None:
    folder = make_style(tmp_path, EVERYTHING.replace("assets/mask.png", "../mask.png"))
    (folder / "assets").mkdir()
    for name in ("tape.png", "paper.png"):
        Image.new("RGBA", (8, 8)).save(folder / "assets" / name)
    with pytest.raises(StyleError, match="inside the style folder"):
        load_style(folder)


def test_radial_spot_fades_to_nothing_at_its_radius() -> None:
    spot = radial_spot(
        (200, 200), RadialSpot(kind="radial", center=(50, 50), radius=25, color="#FF0000FF")
    )
    alpha = spot.getchannel("A")
    assert alpha.getpixel((100, 100)) > 240  # type: ignore[operator]
    assert alpha.getpixel((100, 100 - 50 + 2)) < 20  # type: ignore[operator]
    assert alpha.getpixel((100 - 50 - 2, 100)) == 0  # past the radius on the side
    assert alpha.getpixel((60, 60)) == 0  # past the radius towards the corner


def test_linear_gradient_follows_the_css_angle() -> None:
    stops = [Stop(at=0, color="#000000"), Stop(at=1, color="#FFFFFF")]
    down = linear_gradient((100, 60), LinearGradient(kind="linear", angle=180, stops=stops))
    right = linear_gradient((100, 60), LinearGradient(kind="linear", angle=90, stops=stops))
    assert down.getpixel((50, 1))[0] < 20 and down.getpixel((50, 58))[0] > 235  # type: ignore[index]
    assert right.getpixel((1, 30))[0] < 20 and right.getpixel((98, 30))[0] > 235  # type: ignore[index]


def test_letter_spacing_widens_the_line() -> None:
    plain = font_measure(MONTSERRAT)
    spaced = font_measure(MONTSERRAT, spacing=0.1)
    assert spaced("ABCD", 50) == pytest.approx(plain("ABCD", 50) + 3 * 5)
    assert spaced("A", 50) == pytest.approx(plain("A", 50))


def test_title_keeps_to_the_height() -> None:
    free = fit("WINTER", 600, 10, 300, 2, MEASURE)
    low = fit("WINTER", 600, 10, 300, 2, MEASURE, height=60, line_height=1.0)
    assert free.size > 100
    assert low.size <= 50


def test_vignette_darkens_the_corners_only() -> None:
    layer = vignette((200, 100), Vignette(kind="vignette", inner=0.5, color="#000000FF"))
    alpha = layer.getchannel("A")
    assert alpha.getpixel((100, 50)) == 0
    assert alpha.getpixel((0, 0)) > 200  # type: ignore[operator]


def test_pin_goes_over_the_note(styles: dict[str, Style]) -> None:
    """The board's pin is drawn after the title's note, so the note does not hide it."""
    board = styles["board"]
    output, _ = board.output(OutputKind.SERIES_POSTER)
    pins = [item for item in output.decor if item.above_text]
    assert pins
    with_title = render(board, OutputKind.SERIES_POSTER, FRAMES[:1], "Winter", 1).image
    x = round((pins[0].box[0] + pins[0].box[2] / 2) / 100 * 1000)
    y = round((pins[0].box[1] + pins[0].box[3] / 2) / 100 * 1500)
    r, g, b, _ = with_title.getpixel((x - 4, y - 4))  # type: ignore[misc]
    assert min(r, g, b) > 200, "the white pin head, not the note's paper shade"


# --- faces kept out from under the title ------------------------------------------------


def _red_rows(image: Image.Image) -> list[int]:
    """Rows of the middle column that are red (the "face" in these tests)."""
    rows = []
    for y in range(image.height):
        pixel = image.getpixel((image.width // 2, y))
        if isinstance(pixel, tuple) and pixel[0] > 200 and pixel[1] < 80:
            rows.append(y)
    return rows


def test_faces_go_to_the_part_the_title_leaves_free() -> None:
    """A tall frame with a face in its middle, in a square cell whose lower half the title
    covers: the face moves up into the free half."""
    frame = Image.new("RGB", (100, 200), (40, 90, 40))
    frame.paste((230, 30, 30), (30, 90, 70, 120))  # the face
    region = (0.3, 0.45, 0.4, 0.15)
    plain = cover(frame, (100, 100), (0.5, 0.52), region)
    free = cover(frame, (100, 100), (0.5, 0.52), region, space=(0, 0, 100, 50))
    assert max(_red_rows(plain)) > 50, "without the title the face would be low"
    assert _red_rows(free) and max(_red_rows(free)) <= 50


def test_frame_is_enlarged_only_when_it_must_be() -> None:
    """A frame as wide as the cell cannot move sideways: to get the face out from under a
    title on the right, it is enlarged; with room to move, it is not."""
    frame = Image.new("RGB", (200, 100), (40, 90, 40))
    frame.paste((230, 30, 30), (130, 40, 150, 60))
    region = (0.65, 0.4, 0.1, 0.2)
    moved = cover(frame, (200, 100), (0.7, 0.5), region, space=(0, 0, 120, 100))
    columns = [x for x in range(200) if moved.getpixel((x, 50))[0] > 200]  # type: ignore[index]
    assert columns and max(columns) <= 120
    assert len(columns) > 20, "enlarged: the face is wider than in the frame"
    loose = Image.new("RGB", (400, 100), (40, 90, 40))
    loose.paste((230, 30, 30), (300, 40, 320, 60))
    shifted = cover(loose, (200, 100), (0.775, 0.5), (0.75, 0.4, 0.05, 0.2), (0, 0, 120, 100))
    columns = [x for x in range(200) if shifted.getpixel((x, 50))[0] > 200]  # type: ignore[index]
    assert columns and max(columns) <= 120 and len(columns) <= 21, "moved, not enlarged"


def test_free_space_is_the_largest_part_beside_the_title() -> None:
    cell = (0.0, 0.0, 100.0, 200.0)
    assert free_space(cell, (0, 150, 100, 200)) == (0, 0, 100, 150)
    assert free_space(cell, (0, 0, 100, 40)) == (0, 40, 100, 200)
    assert free_space(cell, (500, 500, 600, 600)) is None, "the title is elsewhere"
    assert free_space(cell, (0, 10, 100, 190)) is None, "too little is left"
    assert free_space(cell, None) is None


def test_diamond_has_rounded_corners_and_a_border_along_its_edge(tmp_path: Path) -> None:
    from showrunner.artwork.style import CellStyle

    sharp = shape_mask((200, 200), CellStyle(shape="diamond"), 1.0, lambda name: tmp_path / name)
    round_ = shape_mask(
        (200, 200), CellStyle(shape="diamond", radius=30), 1.0, lambda name: tmp_path / name
    )
    assert sharp.getpixel((100, 3)) > 100  # type: ignore[operator]
    assert round_.getpixel((100, 3)) < 50  # type: ignore[operator]
    assert sharp.getpixel((100, 100)) == round_.getpixel((100, 100)) == 255
    assert sharp.getpixel((5, 5)) == 0


def test_visible_part_of_a_slanted_band_and_a_diamond(tmp_path: Path) -> None:
    from showrunner.artwork.style import CellStyle

    band = CellStyle(shape="polygon", points=[(0, 0), (100, 40), (100, 100), (0, 60)])
    mask = shape_mask((200, 100), band, 1.0, lambda name: tmp_path / name)
    box = visible_part(mask)
    assert box is not None
    assert box[0] == 0 and box[2] == 200, "a band: full rows"
    assert 38 <= box[1] <= 42 and 58 <= box[3] <= 62
    diamond = shape_mask((200, 200), CellStyle(shape="diamond"), 1.0, lambda n: tmp_path / n)
    middle = visible_part(diamond)
    assert middle is not None
    assert middle[0] == pytest.approx(50, abs=4) and middle[2] == pytest.approx(150, abs=4)
    assert visible_part(Image.new("L", (50, 50), 255)) is None, "a full cell needs no limit"
