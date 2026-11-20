# SPDX-License-Identifier: AGPL-3.0-or-later
"""Models for slideshows: downloaded once into the data folder, kept only when they are the
model, tried again an hour after a failure; and the embeddings made with CLIP."""

import hashlib
import os
from pathlib import Path

import httpx2
import numpy as np
import pytest
from PIL import Image

from showrunner.slideshow import models
from showrunner.slideshow.embed import SIDE, Embedder, pack, prepare, similarity, unpack
from showrunner.slideshow.models import CLIP, ModelFile, ensure, model_path

CONTENT = b"a tiny model " * 1000


def tiny(content: bytes = CONTENT) -> ModelFile:
    return ModelFile(
        name="tiny",
        file="model.onnx",
        url="https://models.test/tiny/model.onnx",
        size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        license="MIT",
    )


class Server:
    def __init__(self, body: bytes, status: int = 200) -> None:
        self.body, self.status, self.calls = body, status, 0

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        self.calls += 1
        if request.url.host == "models.test":
            # As Hugging Face does: on to where the file is.
            return httpx2.Response(302, headers={"location": "https://cdn.models.test/blob"})
        return httpx2.Response(self.status, content=self.body)

    def transport(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self.handler)


@pytest.fixture(autouse=True)
def fresh() -> None:
    models.forget_failures()


@pytest.mark.anyio
async def test_a_model_is_downloaded_once(tmp_path: Path) -> None:
    server = Server(CONTENT)
    path = await ensure(tiny(), tmp_path, transport=server.transport())
    assert path == model_path(tiny(), tmp_path)
    assert path is not None and path.read_bytes() == CONTENT
    calls = server.calls
    assert await ensure(tiny(), tmp_path, transport=server.transport()) == path
    assert server.calls == calls, "there already: not downloaded again"


@pytest.mark.anyio
async def test_a_file_that_is_not_the_model_is_not_kept(tmp_path: Path) -> None:
    server = Server(b"x" * len(CONTENT))
    assert await ensure(tiny(), tmp_path, transport=server.transport()) is None
    folder = model_path(tiny(), tmp_path).parent
    assert list(folder.iterdir()) == [], "neither the model nor a partial file"


@pytest.mark.anyio
async def test_after_a_failure_the_download_waits_an_hour(tmp_path: Path) -> None:
    down = Server(b"", status=503)
    assert await ensure(tiny(), tmp_path, transport=down.transport(), clock=1000.0) is None
    up = Server(CONTENT)
    assert await ensure(tiny(), tmp_path, transport=up.transport(), clock=1500.0) is None
    assert up.calls == 0
    path = await ensure(tiny(), tmp_path, transport=up.transport(), clock=1000.0 + 3601)
    assert path is not None


@pytest.mark.anyio
async def test_without_a_data_folder_there_is_no_model() -> None:
    assert await ensure(tiny(), None) is None


def test_the_clip_model_is_pinned() -> None:
    assert "/resolve/19a057a0fb927cf239541300e74237cd56c7ffe2/" in CLIP.url
    assert len(CLIP.sha256) == 64
    assert CLIP.id.startswith("clip-vit-b-32-laion2b@")


def test_a_photo_is_prepared_as_openclip_prepares_it() -> None:
    portrait = Image.new("RGB", (300, 600), (255, 0, 0))
    portrait.paste((0, 0, 255), (0, 0, 300, 100))  # at the top: cut off with the rest above
    x = prepare(portrait)
    assert x.shape == (1, 3, SIDE, SIDE)
    assert x.dtype == np.float32
    # Pure red, normalized: (1 - mean) / std in the red channel, everywhere in the middle cut.
    assert np.allclose(x[0, 0], (1 - 0.48145466) / 0.26862954, atol=1e-3)


def test_an_embedding_is_kept_in_one_kilobyte() -> None:
    vector = np.random.default_rng(1).standard_normal(512).astype(np.float32)
    vector /= np.linalg.norm(vector)
    data = pack(vector)
    assert len(data) == 1024
    assert similarity(unpack(data), vector) > 0.9999
    with pytest.raises(ValueError):
        pack(vector[:10])


MODEL = os.environ.get("SHOWRUNNER_TEST_CLIP_MODEL", "")


@pytest.mark.skipif(not MODEL, reason="SHOWRUNNER_TEST_CLIP_MODEL is not set (the 351 MB model)")
def test_the_real_model_tells_alike_photos() -> None:
    rng = np.random.default_rng(3)
    base = (rng.random((48, 64, 3)) * 255).astype(np.uint8)
    photo = Image.fromarray(base).resize((640, 480), Image.Resampling.BICUBIC)
    copy = photo.resize((600, 450)).rotate(2)
    other = Image.fromarray(255 - base[::-1]).resize((640, 480), Image.Resampling.NEAREST)
    embedder = Embedder(Path(MODEL))
    a, b, c = (embedder.embed(p) for p in (photo, copy, other))
    assert abs(float(np.linalg.norm(a)) - 1) < 1e-4
    assert similarity(a, b) > similarity(a, c)
    assert similarity(a, b) > 0.8
