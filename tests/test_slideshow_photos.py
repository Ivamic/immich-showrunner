# SPDX-License-Identifier: AGPL-3.0-or-later
"""Photos for slideshows: opened upright and small, looked at once and kept, near copies told
by their hash; in the sync, photos are looked at within the time budget and an album with photos
still to look at is read again on the next pass."""

import io
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import UUID

import numpy as np
import pytest
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from fake_immich import FakeImmich, asset_id
from showrunner.artwork.faces import FaceDetector
from showrunner.config import parse_path_map
from showrunner.immich.models import Asset
from showrunner.model.show import Options
from showrunner.slideshow.models import CLIP
from showrunner.slideshow.photos import (
    PHOTO_LOOK_VERSION,
    PhotoError,
    PhotoLook,
    distance,
    look_at_photo,
    look_version,
    open_photo,
    phash,
)
from showrunner.store.registry import Registry
from showrunner.sync.executor import Executor
from showrunner.sync.service import Output, sync_outputs
from showrunner.sync.slideshow import SlideshowContext, plan_inputs
from showrunner.targets.jellyfin.layout import JellyfinLayout

DATA = Path(__file__).parent / "data"
OPTIONS = Options(path_mappings=parse_path_map("/data=/mnt/immich"), show_prefix="◈ ")


def scene(width: int = 800, height: int = 600, seed: int = 1) -> Image.Image:
    """A synthetic photo: soft gradients and a few blocks, different for each seed."""
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:height, 0:width].astype(np.float32)
    base = rng.uniform(40, 200, 3)
    layers = [
        base[c] + 50 * np.sin(x / (60 + 25 * c) + seed) * np.cos(y / (80 + 10 * seed))
        for c in range(3)
    ]
    rgb = np.clip(np.stack(layers, -1), 0, 255).astype(np.uint8)
    for _ in range(6):
        x0, y0 = int(rng.integers(0, width - 100)), int(rng.integers(0, height - 100))
        rgb[y0 : y0 + 90, x0 : x0 + 90] = rng.integers(0, 255, 3)
    return Image.fromarray(rgb)


def jpeg(picture: Image.Image, *, orientation: int = 1, quality: int = 90) -> bytes:
    exif = Image.Exif()
    exif[0x0112] = orientation
    out = io.BytesIO()
    picture.save(out, "JPEG", quality=quality, exif=exif)
    return out.getvalue()


# --- one photo ----------------------------------------------------------------------------


def test_a_photo_is_turned_upright_as_its_exif_says() -> None:
    stored = scene(800, 600)
    picture, given = open_photo(jpeg(stored, orientation=6))
    assert picture.size == (600, 800), "orientation 6: turned a quarter clockwise"
    assert given == 800
    assert picture.mode == "RGB"


def test_a_large_photo_is_opened_small() -> None:
    picture, given = open_photo(jpeg(scene(4000, 3000)), long_side=1000)
    assert max(picture.size) == 1000
    assert given == 4000


def test_a_photo_with_transparency_is_put_on_white() -> None:
    out = io.BytesIO()
    Image.new("RGBA", (40, 30), (255, 0, 0, 0)).save(out, "PNG")
    picture, _ = open_photo(out.getvalue())
    assert picture.getpixel((5, 5)) == (255, 255, 255)


def test_what_is_not_a_photo_is_refused() -> None:
    with pytest.raises(PhotoError):
        open_photo(b"not a photo at all")


def test_near_copies_are_close_by_their_hash_and_other_photos_are_not() -> None:
    photo = scene(seed=1)
    copy = photo.resize((400, 300)).copy()
    recompressed, _ = open_photo(jpeg(copy, quality=60))
    other = scene(seed=2)
    assert distance(phash(photo), phash(photo)) == 0
    assert distance(phash(photo), phash(recompressed)) <= 6
    assert distance(phash(photo), phash(other)) >= 16


def test_a_look_finds_the_face_and_survives_the_database() -> None:
    content = (DATA / "portrait.jpg").read_bytes()
    found = look_at_photo(str(asset_id(1)), content, FaceDetector())
    assert found.frame.faces, "the portrait has a face"
    assert found.frame.region is not None
    data = found.to_dict()
    assert data["v"] == PHOTO_LOOK_VERSION
    kept = PhotoLook.from_dict(data)
    assert kept is not None and kept.to_dict() == data, "kept as written (rounded)"
    assert PhotoLook.from_dict({**data, "v": PHOTO_LOOK_VERSION + 1}) is None
    assert PhotoLook.from_dict({**data, "frame": {**data["frame"], "v": -1}}) is None


# --- in the sync --------------------------------------------------------------------------


class FakeSlideshow(SlideshowContext):
    """Looks at the photos in this process (with the real code), not in the worker. With
    `model`, the embedding is a made-up one: the last bytes of the photo."""

    def __init__(self, *, full: bool = True, budget: float = 60.0, model: bool = False) -> None:
        super().__init__(full=full, budget_seconds=budget, worker=None)  # type: ignore[arg-type]
        self.looked: list[UUID] = []
        self.has_model = model
        self._detector = FaceDetector()

    async def model(self) -> Path | None:
        return Path("/models/clip.onnx") if self.has_model else None

    async def look(
        self, asset_id: UUID, content: bytes, model: Path | None
    ) -> tuple[PhotoLook, bytes | None]:
        self.looked.append(asset_id)
        found = look_at_photo(str(asset_id), content, self._detector)
        return found, (b"EMB" + content[-8:] if model is not None else None)


def album_of_photos(immich: FakeImmich | None = None) -> tuple[FakeImmich, UUID]:
    immich = immich or FakeImmich()
    album = immich.add_album(1, "Holidays")
    immich.add_photo(album, 11, "2023-07-01T10:00:00", jpeg(scene(seed=1)), size=(800, 600))
    immich.add_photo(album, 12, "2023-07-01T10:00:05", jpeg(scene(seed=3)), size=(800, 600))
    return immich, album


async def one_pass(
    immich: FakeImmich, session: AsyncSession, out: Path, slideshow: FakeSlideshow
) -> Any:
    async with immich.client() as client:
        (report,) = await sync_outputs(
            immich=client,
            registry=Registry(session),
            outputs=[Output(JellyfinLayout(), Executor(out, [PurePosixPath("/mnt/immich")]))],
            options=OPTIONS,
            full=False,
            slideshow=slideshow,
        )
    return report


def downloads(immich: FakeImmich) -> list[str]:
    return [r for r in immich.requests if r.endswith("/thumbnail")]


@pytest.mark.anyio
async def test_photos_are_looked_at_once_and_kept(session: AsyncSession, tmp_path: Path) -> None:
    immich, album = album_of_photos()
    first = FakeSlideshow()
    report = await one_pass(immich, session, tmp_path, first)
    assert report.ok
    assert sorted(first.looked) == [asset_id(11), asset_id(12)]
    assert f"GET /api/assets/{asset_id(11)}/original" in immich.requests, "full size: original"
    rows = await Registry(session).photo_looks([asset_id(11), asset_id(12)])
    assert {row.version for row in rows.values()} == {look_version()}
    kept = PhotoLook.from_dict(rows[asset_id(11)].look)
    assert kept is not None and kept.given_side == 800

    immich.touch(album, "2026-02-01T00:00:00.000Z")
    immich.requests.clear()
    again = FakeSlideshow()
    await one_pass(immich, session, tmp_path, again)
    assert again.looked == [], "nothing new: nothing is looked at again"
    assert downloads(immich) == [], "nor downloaded"


@pytest.mark.anyio
async def test_a_replaced_photo_is_looked_at_again(session: AsyncSession, tmp_path: Path) -> None:
    immich, album = album_of_photos()
    await one_pass(immich, session, tmp_path, FakeSlideshow())
    immich.photos[album][0]["checksum"] = "sum2"
    immich.photo_files[str(asset_id(11))] = jpeg(scene(seed=5))
    immich.touch(album, "2026-02-01T00:00:00.000Z")
    again = FakeSlideshow()
    await one_pass(immich, session, tmp_path, again)
    assert again.looked == [asset_id(11)]


@pytest.mark.anyio
async def test_a_photo_edited_in_immich_is_looked_at_again_as_edited(
    session: AsyncSession, tmp_path: Path
) -> None:
    immich, album = album_of_photos()
    await one_pass(immich, session, tmp_path, FakeSlideshow())
    assert not any("edited=" in url for url in immich.urls if "/thumbnail" in url)

    # Turned in Immich: the file and its checksum stay, the edit is new.
    turned = jpeg(scene(seed=5))
    immich.edit_photo(album, 11, turned, thumbhash="turned1")
    immich.touch(album, "2026-02-01T00:00:00.000Z")
    immich.urls.clear()
    again = FakeSlideshow()
    await one_pass(immich, session, tmp_path, again)
    assert again.looked == [asset_id(11)], "only the edited one"
    assert any(f"{asset_id(11)}/thumbnail" in url and "edited=true" in url for url in immich.urls)

    immich.touch(album, "2026-03-01T00:00:00.000Z")
    same = FakeSlideshow()
    await one_pass(immich, session, tmp_path, same)
    assert same.looked == [], "the same edit: not again"

    for n, (content, thumbhash) in enumerate([(turned, "turned2"), (None, "")], start=4):
        immich.edit_photo(album, 11, content, thumbhash=thumbhash)
        immich.touch(album, f"2026-0{n}-01T00:00:00.000Z")
        later = FakeSlideshow()
        await one_pass(immich, session, tmp_path, later)
        assert later.looked == [asset_id(11)], "another edit, and the edit undone"


@pytest.mark.anyio
async def test_an_album_waits_for_its_photos(session: AsyncSession, tmp_path: Path) -> None:
    immich, _ = album_of_photos()
    waiting = FakeSlideshow(budget=0)
    report = await one_pass(immich, session, tmp_path, waiting)
    assert report.ok
    assert waiting.looked == []
    # Not stamped: the next quick pass reads the album again, though it did not change.
    later = FakeSlideshow()
    await one_pass(immich, session, tmp_path, later)
    assert sorted(later.looked) == [asset_id(11), asset_id(12)]
    done = FakeSlideshow()
    await one_pass(immich, session, tmp_path, done)
    assert done.looked == [], "stamped once every photo was looked at"


@pytest.mark.anyio
async def test_a_photo_that_can_not_be_read_is_not_tried_again(
    session: AsyncSession, tmp_path: Path
) -> None:
    immich, album = album_of_photos()
    immich.photo_files[str(asset_id(12))] = b"broken file"
    first = FakeSlideshow()
    report = await one_pass(immich, session, tmp_path, first)
    assert report.ok, "a broken photo does not stop the pass"
    rows = await Registry(session).photo_looks([asset_id(12)])
    assert rows[asset_id(12)].failed
    immich.touch(album, "2026-02-01T00:00:00.000Z")
    immich.requests.clear()
    again = FakeSlideshow()
    await one_pass(immich, session, tmp_path, again)
    assert downloads(immich) == []


@pytest.mark.anyio
async def test_without_download_the_previews_are_looked_at(
    session: AsyncSession, tmp_path: Path
) -> None:
    immich, _ = album_of_photos()
    await one_pass(immich, session, tmp_path, FakeSlideshow(full=False))
    rows = await Registry(session).photo_looks([asset_id(11)])
    kept = PhotoLook.from_dict(rows[asset_id(11)].look)
    assert kept is not None and kept.given_side == 400, "the preview of the fake is half size"


@pytest.mark.anyio
async def test_a_pass_without_slideshows_looks_at_no_photo(
    session: AsyncSession, tmp_path: Path
) -> None:
    immich, _ = album_of_photos()
    async with immich.client() as client:
        await sync_outputs(
            immich=client,
            registry=Registry(session),
            outputs=[Output(JellyfinLayout(), Executor(tmp_path, [PurePosixPath("/mnt/immich")]))],
            options=OPTIONS,
            full=False,
        )
    assert downloads(immich) == []


@pytest.mark.anyio
async def test_a_photo_is_tried_again_when_immich_fails(
    session: AsyncSession, tmp_path: Path
) -> None:
    immich, _ = album_of_photos()
    immich.broken[f"/api/assets/{asset_id(11)}/"] = 503
    report = await one_pass(immich, session, tmp_path, FakeSlideshow())
    assert report.ok
    assert await Registry(session).photo_looks([asset_id(11)]) == {}, "nothing kept"
    del immich.broken[f"/api/assets/{asset_id(11)}/"]
    again = FakeSlideshow()
    await one_pass(immich, session, tmp_path, again)
    assert asset_id(11) in again.looked, "the album was not stamped: tried again"


@pytest.mark.anyio
async def test_photos_get_their_embedding_once_the_model_is_there(
    session: AsyncSession, tmp_path: Path
) -> None:
    immich, album = album_of_photos()
    await one_pass(immich, session, tmp_path, FakeSlideshow(model=False))
    rows = await Registry(session).photo_looks([asset_id(11)])
    assert rows[asset_id(11)].embedding is None
    assert rows[asset_id(11)].embedding_model is None

    # The model came: a quick pass does not read the album again (it did not change) …
    quick = FakeSlideshow(model=True)
    await one_pass(immich, session, tmp_path, quick)
    assert quick.looked == []
    # … a full pass looks at its photos again for their embeddings, and only once.
    full = FakeSlideshow(model=True)
    async with immich.client() as client:
        await sync_outputs(
            immich=client,
            registry=Registry(session),
            outputs=[Output(JellyfinLayout(), Executor(tmp_path, [PurePosixPath("/mnt/immich")]))],
            options=OPTIONS,
            full=True,
            slideshow=full,
        )
    assert sorted(full.looked) == [asset_id(11), asset_id(12)]
    rows = await Registry(session).photo_looks([asset_id(11)])
    embedding = rows[asset_id(11)].embedding
    assert embedding is not None and embedding.startswith(b"EMB")
    assert rows[asset_id(11)].embedding_model == CLIP.id
    again = FakeSlideshow(model=True)
    immich.touch(album, "2026-03-01T00:00:00.000Z")
    await one_pass(immich, session, tmp_path, again)
    assert again.looked == []


@pytest.mark.anyio
async def test_without_the_model_an_album_is_not_held_back(
    session: AsyncSession, tmp_path: Path
) -> None:
    immich, _ = album_of_photos()
    report = await one_pass(immich, session, tmp_path, FakeSlideshow(model=False))
    assert report.ok
    later = FakeSlideshow(model=False)
    await one_pass(immich, session, tmp_path, later)
    assert later.looked == [], "the album was stamped: no embedding is no reason to read it again"


@pytest.mark.anyio
async def test_the_photos_looked_at_are_what_the_cut_list_starts_from(
    session: AsyncSession, tmp_path: Path
) -> None:
    immich, album = album_of_photos()
    immich.photo_files[str(asset_id(12))] = b"broken file"
    await one_pass(immich, session, tmp_path, FakeSlideshow(model=False))
    assets = [Asset.model_validate(p) for p in immich.photos[album]]
    rows = await Registry(session).photo_looks([a.id for a in assets])
    inputs = plan_inputs(assets, rows)
    assert [p.asset_id for p in inputs] == [asset_id(11)], "the broken one is not there"
    (first,) = inputs
    assert first.taken == datetime(2023, 7, 1, 10, 0)
    assert (first.latitude, first.longitude) == (43.7, 7.26)
    assert first.embedding is None
