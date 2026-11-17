# SPDX-License-Identifier: AGPL-3.0-or-later
"""Frames for artwork: read from a video over HTTP, looked at, cropped around faces, chosen.

The video is made here; the portrait in tests/data is in the public domain (see
THIRD_PARTY_NOTICES.md)."""

import contextlib
import http.server
import threading
from collections.abc import Iterator
from fractions import Fraction
from pathlib import Path

import av
import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFilter

from showrunner.artwork.faces import Face, FaceDetector
from showrunner.artwork.focus import focus, salient_point
from showrunner.artwork.frames import FrameError, grab, points, seconds, trim_bars
from showrunner.artwork.paint import cover
from showrunner.artwork.quality import assess
from showrunner.artwork.select import FrameLook, choose, likeness, look

PORTRAIT = Path(__file__).parent / "data" / "portrait.jpg"
COLORS = [(220, 40, 40), (40, 200, 40), (40, 40, 220), (220, 220, 40)]
"""One color for each second of the test video."""


@pytest.fixture(scope="module")
def detector() -> FaceDetector:
    return FaceDetector()


# --- reading frames ---------------------------------------------------------------------


@pytest.fixture(scope="module")
def video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Four seconds, a key frame every second, each second its own color, black bars on top
    and bottom (a letterboxed film)."""
    path = tmp_path_factory.mktemp("video") / "clip.mp4"
    with av.open(str(path), "w") as out:
        stream = out.add_stream("mpeg4", rate=25)
        stream.width, stream.height, stream.pix_fmt = 320, 240, "yuv420p"
        stream.codec_context.gop_size = 25
        for i in range(100):
            image = Image.new("RGB", (320, 240), (0, 0, 0))
            ImageDraw.Draw(image).rectangle((0, 30, 319, 209), fill=COLORS[i // 25])
            frame = av.VideoFrame.from_image(image)  # type: ignore[no-untyped-call]
            frame.pts, frame.time_base = i, Fraction(1, 25)
            for packet in stream.encode(frame):
                out.mux(packet)
        for packet in stream.encode():
            out.mux(packet)
    return path


class RangeHandler(http.server.BaseHTTPRequestHandler):
    """Serves one file with byte ranges, and only with the right key."""

    file: Path

    def log_message(self, *args: object) -> None:
        pass

    def do_GET(self) -> None:
        if self.headers.get("x-api-key") != "secret":
            self.send_error(403)
            return
        data = self.file.read_bytes()
        start, end = 0, len(data) - 1
        if self.headers.get("Range", "").startswith("bytes="):
            first, _, last = self.headers["Range"][6:].partition("-")
            start, end = int(first), int(last) if last else len(data) - 1
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{len(data)}")
        else:
            self.send_response(200)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        with contextlib.suppress(BrokenPipeError, ConnectionResetError):
            self.wfile.write(data[start : end + 1])


@pytest.fixture
def served(video: Path) -> Iterator[str]:
    handler = type("Handler", (RangeHandler,), {"file": video})
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/api/assets/x/original"
    server.shutdown()


def _color(image: Image.Image) -> tuple[int, ...]:
    middle = image.convert("RGB").getpixel((image.width // 2, image.height // 2))
    assert isinstance(middle, tuple)
    return middle


def _near(a: tuple[int, ...], b: tuple[int, ...]) -> bool:
    return all(abs(x - y) < 40 for x, y in zip(a, b, strict=True))


def test_frames_come_from_their_time_over_http(served: str) -> None:
    grabs = grab(served, points(4.0, 4), headers={"x-api-key": "secret"})
    assert [g.at for g in grabs] == [0.5, 1.5, 2.5, 3.5]
    for g, color in zip(grabs, COLORS, strict=True):
        assert _near(_color(g.image), color), (g.at, _color(g.image))
        assert g.image.size == (320, 180), "the black bars are cut off"


def test_the_same_time_gives_the_same_frame(video: Path) -> None:
    first = grab(str(video), [2.2])[0].image
    again = grab(str(video), [2.2])[0].image
    assert first.tobytes() == again.tobytes()


def test_wrong_key_is_an_error(served: str) -> None:
    with pytest.raises(FrameError):
        grab(served, [1.0], headers={"x-api-key": "wrong"})


def test_not_a_video_is_an_error(tmp_path: Path) -> None:
    (tmp_path / "note.txt").write_text("not a video")
    with pytest.raises(FrameError):
        grab(str(tmp_path / "note.txt"), [1.0])


@pytest.mark.parametrize(
    ("duration", "expected"),
    [("0:01:05.500000", 65.5), (65500, 65.5), (None, 0.0), ("", 0.0), ("broken", 0.0)],
)
def test_duration_from_both_immich_versions(duration: str | int | None, expected: float) -> None:
    assert seconds(duration) == expected


def test_points_are_spread_evenly() -> None:
    assert points(60, 6) == [5.0, 15.0, 25.0, 35.0, 45.0, 55.0]
    assert points(0, 6) == [0.0]


def test_trim_bars_keeps_a_dark_picture() -> None:
    night = Image.new("RGB", (200, 100), (5, 5, 5))
    assert trim_bars(night).size == (200, 100)
    pillar = Image.new("RGB", (200, 100), (0, 0, 0))
    pillar.paste((120, 120, 120), (30, 0, 170, 100))
    assert trim_bars(pillar).size == (140, 100)


# --- looking at frames ------------------------------------------------------------------


def busy(size: tuple[int, int] = (640, 360), seed: int = 0) -> Image.Image:
    """A sharp, colorful picture: random blocks."""
    rng = np.random.default_rng(seed)
    blocks = rng.integers(0, 255, (size[1] // 20, size[0] // 20, 3), dtype=np.uint8)
    return Image.fromarray(blocks).resize(size, Image.Resampling.NEAREST)


def test_sharp_beats_blurred_and_dark() -> None:
    sharp = assess(busy())
    blurred = assess(busy().filter(ImageFilter.GaussianBlur(8)))
    dark = assess(busy().point(lambda v: v // 8))
    black = assess(Image.new("RGB", (640, 360)))
    assert sharp.score > blurred.score > black.score
    assert sharp.score > dark.score > black.score
    assert sharp.sharpness > 0.9 > 0.3 > blurred.sharpness
    assert black.clipped == 1.0


def test_small_frame_scores_lower() -> None:
    assert assess(busy((320, 180))).score < assess(busy((1280, 720))).score


def test_faces_are_found(detector: FaceDetector) -> None:
    faces = detector.detect(Image.open(PORTRAIT))
    assert len(faces) == 1
    x, y, w, h = faces[0].box
    assert 0.25 < x + w / 2 < 0.75 and 0.2 < y + h / 2 < 0.6
    assert detector.detect(busy()) == []


def test_crop_keeps_the_faces(detector: FaceDetector) -> None:
    """A portrait moved to the right edge of a wide frame: a narrow crop must show the face."""
    portrait = Image.open(PORTRAIT).convert("RGB")
    wide = Image.new("RGB", (1200, 360), (90, 120, 90))
    wide.paste(portrait, (1200 - portrait.width, 0))
    faces = detector.detect(wide)
    assert faces
    where = focus(wide, faces)
    assert where.region is not None
    narrow = cover(wide, (120, 360), where.point, where.region)
    centered = cover(wide, (120, 360))
    assert detector.detect(narrow.convert("RGB")), "the face is in the crop"
    assert not detector.detect(centered.convert("RGB"))


def test_salient_point_finds_the_thing() -> None:
    plain = Image.new("RGB", (400, 200), (128, 140, 150))
    plain.paste(busy((60, 60)), (300, 120))
    x, y = salient_point(plain)
    assert x > 0.65 and y > 0.55


def test_cover_keeps_the_region_whole() -> None:
    image = Image.new("RGB", (1000, 100), (0, 0, 0))
    image.paste((255, 0, 0), (700, 0, 800, 100))
    # The focus asks for the left, the region is on the right: the region wins.
    crop = cover(image, (300, 100), focus=(0.1, 0.5), region=(0.7, 0.0, 0.1, 1.0))
    row = [crop.getpixel((x, 50)) for x in range(300)]
    reds = sum(1 for pixel in row if isinstance(pixel, tuple) and pixel[0] > 200)
    assert reds >= 98


# --- choosing ---------------------------------------------------------------------------


def make_look(asset: str, at: float, image: Image.Image, detector: FaceDetector) -> FrameLook:
    return look(asset, at, image, detector)


def test_look_survives_the_cache(detector: FaceDetector) -> None:
    item = look("a", 1.5, Image.open(PORTRAIT).convert("RGB"), detector)
    again = FrameLook.from_dict(item.to_dict())
    assert again is not None
    assert again.to_dict() == item.to_dict()
    assert FrameLook.from_dict({**item.to_dict(), "v": 0}) is None


def test_choice_skips_repeats_and_spreads_over_videos(detector: FaceDetector) -> None:
    looks = [make_look("v1", t, busy(seed=1), detector) for t in (1.0, 2.0, 3.0)]  # one scene
    looks += [make_look("v1", 4.0, busy(seed=2), detector)]
    looks += [make_look("v2", t, busy(seed=int(10 + t)), detector) for t in (1.0, 2.0)]
    looks += [make_look("v3", 1.0, Image.new("RGB", (640, 360)), detector)]  # black
    chosen = choose(looks, 4)
    assert len(chosen) == 4
    assert sum(1 for c in chosen if c.signature == looks[0].signature) == 1, "no repeats"
    assert {c.asset_id for c in chosen} >= {"v1", "v2"}
    assert all(c.asset_id != "v3" for c in chosen), "the black frame is left out"
    assert likeness(looks[0], looks[1]) == 1.0
    assert choose(looks, 4) == chosen, "same seed, same choice"


def test_black_frame_is_taken_when_nothing_else_is_left(detector: FaceDetector) -> None:
    black = make_look("v", 1.0, Image.new("RGB", (640, 360)), detector)
    assert choose([black], 3) == [black]


def test_faces_come_first(detector: FaceDetector) -> None:
    """Two equally sharp frames: the one with a face is taken first."""
    with_face_image = busy((1280, 720), seed=5)
    with_face_image.paste(Image.open(PORTRAIT).convert("RGB"), (500, 200))
    with_face = make_look("a", 1.0, with_face_image, detector)
    scenery = make_look("b", 1.0, busy((1280, 720), seed=6), detector)
    assert with_face.faces and not scenery.faces
    assert choose([scenery, with_face], 2)[0] is with_face


def test_seed_gives_other_frames(detector: FaceDetector) -> None:
    looks = [make_look(f"v{i}", 1.0, busy(seed=i), detector) for i in range(12)]
    choices = {tuple(c.asset_id for c in choose(looks, 4, seed)) for seed in range(6)}
    assert len(choices) > 1


def test_face_box_helpers() -> None:
    face = Face(box=(0.1, 0.2, 0.3, 0.4), score=0.9)
    assert face.area == pytest.approx(0.12)
    assert face.center == pytest.approx((0.25, 0.4))
