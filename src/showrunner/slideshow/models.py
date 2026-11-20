# SPDX-License-Identifier: AGPL-3.0-or-later
"""Models the slideshows use, downloaded on first use into the data folder of the app.

They are too large for the image, so each is fetched once from a fixed revision and kept only
when its size and SHA-256 are the ones written here. A file is written under a temporary name and
renamed when it is checked, so a stopped download never looks like a model. Without a network the
slideshows go on without the model; the download is tried again an hour later."""

from __future__ import annotations

import hashlib
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

import httpx2

log = logging.getLogger(__name__)

RETRY_AFTER_S = 3600.0
CHUNK = 1 << 20


@dataclass(frozen=True)
class ModelFile:
    name: str
    """Folder of the model in the data folder, and its name in the logs."""
    file: str
    url: str
    size: int
    sha256: str
    license: str

    @property
    def id(self) -> str:
        """What a result made with this model is marked with: another model, another mark."""
        return f"{self.name}@{self.sha256[:12]}"


CLIP = ModelFile(
    name="clip-vit-b-32-laion2b",
    file="visual.onnx",
    # OpenCLIP ViT-B/32 trained on LAION-2B, exported to ONNX by Immich.
    url=(
        "https://huggingface.co/immich-app/ViT-B-32__laion2b-s34b-b79k/resolve/"
        "19a057a0fb927cf239541300e74237cd56c7ffe2/visual/model.onnx"
    ),
    size=351_613_724,
    sha256="b9ce24b91a8c62ef8d40ea786051709c93140104cbf2b6b4a2cc270df3838f9c",
    license="MIT",
)

_failed_at: dict[str, float] = {}


def model_path(model: ModelFile, data_dir: Path) -> Path:
    return data_dir / "models" / model.name / model.file


def present(model: ModelFile, data_dir: Path) -> Path | None:
    """The model when it is there: a file of its size is one that was checked."""
    path = model_path(model, data_dir)
    try:
        return path if path.stat().st_size == model.size else None
    except OSError:
        return None


async def ensure(
    model: ModelFile,
    data_dir: Path | None,
    *,
    transport: httpx2.AsyncBaseTransport | None = None,
    clock: float | None = None,
) -> Path | None:
    """The path of the model, downloaded first when it is missing; None when it can not be had
    now (no data folder, no network, a file that is not the model)."""
    if data_dir is None:
        return None
    found = present(model, data_dir)
    if found is not None:
        return found
    now = time.monotonic() if clock is None else clock
    failed = _failed_at.get(model.name)
    if failed is not None and now - failed < RETRY_AFTER_S:
        return None
    try:
        path = await _download(model, data_dir, transport)
    except (httpx2.HTTPError, OSError, ValueError) as exc:
        _failed_at[model.name] = now
        log.warning(
            "the model %s could not be downloaded, slideshows go on without it and it is tried "
            "again in an hour: %s",
            model.name,
            exc,
        )
        return None
    _failed_at.pop(model.name, None)
    return path


async def _download(
    model: ModelFile, data_dir: Path, transport: httpx2.AsyncBaseTransport | None
) -> Path:
    path = model_path(model, data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(f".{path.name}.part")
    log.info("downloading the model %s (%d MB, %s)", model.name, model.size >> 20, model.license)
    digest = hashlib.sha256()
    size = 0
    try:
        async with (
            httpx2.AsyncClient(
                transport=transport, follow_redirects=True, timeout=httpx2.Timeout(60.0)
            ) as client,
            client.stream("GET", model.url) as response,
        ):
            response.raise_for_status()
            with partial.open("wb") as out:
                async for chunk in response.aiter_bytes(CHUNK):
                    size += len(chunk)
                    if size > model.size:
                        raise ValueError(f"it is larger than {model.size} bytes")
                    digest.update(chunk)
                    out.write(chunk)
        if size != model.size or digest.hexdigest() != model.sha256:
            raise ValueError(
                f"it is not the model: {size} bytes, sha256 {digest.hexdigest()[:16]}…"
            )
        os.replace(partial, path)
    finally:
        partial.unlink(missing_ok=True)
    log.info("the model %s is ready", model.name)
    return path


def forget_failures() -> None:
    """For the tests: try downloads again at once."""
    _failed_at.clear()
