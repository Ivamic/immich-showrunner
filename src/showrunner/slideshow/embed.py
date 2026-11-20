# SPDX-License-Identifier: AGPL-3.0-or-later
"""Embeddings of photos: 512 numbers from CLIP (ViT-B/32) that are close for photos that look
alike. They tell near copies, scenes and the order within a scene, and with prepared embeddings
of words they tell what a photo shows (a screenshot, a beach).

The model runs in OpenCV (its DNN module), on the CPU, in the worker process. The photo is
prepared as OpenCLIP prepares it: the short side brought to 224 (bicubic), the middle cut out,
the colours normalized."""

from __future__ import annotations

import threading
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

SIDE = 224
MEAN = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)
STD = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)
SIZE = 512


def prepare(image: Image.Image) -> np.ndarray:
    """The input of the model: 1x3x224x224, float32."""
    picture = image.convert("RGB")
    scale = SIDE / min(picture.size)
    width = max(SIDE, round(picture.width * scale))
    height = max(SIDE, round(picture.height * scale))
    picture = picture.resize((width, height), Image.Resampling.BICUBIC)
    left, top = (width - SIDE) // 2, (height - SIDE) // 2
    picture = picture.crop((left, top, left + SIDE, top + SIDE))
    rgb = np.asarray(picture, dtype=np.float32) / 255
    rgb = (rgb - MEAN) / STD
    return np.ascontiguousarray(rgb.transpose(2, 0, 1)[np.newaxis])


class Embedder:
    """One model for the worker; calls are serialized, as an OpenCV net is not thread-safe."""

    def __init__(self, model: Path) -> None:
        self._net = cv2.dnn.readNetFromONNX(str(model))
        self._lock = threading.Lock()

    def embed(self, image: Image.Image) -> np.ndarray:
        """The embedding of a photo, of length 1."""
        with self._lock:
            self._net.setInput(prepare(image))
            out = self._net.forward()
        return normalized(np.asarray(out, dtype=np.float32).reshape(-1))


def normalized(vector: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    return vector / norm if norm > 0 else vector


def pack(vector: np.ndarray) -> bytes:
    """As kept in the database: float16, 1 KB."""
    if vector.shape != (SIZE,):
        raise ValueError(f"an embedding has {SIZE} numbers, not {vector.shape}")
    return vector.astype("<f2").tobytes()


def unpack(data: bytes) -> np.ndarray:
    return np.frombuffer(data, dtype="<f2").astype(np.float32)


def similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity of two embeddings: near 1 for the same scene."""
    return float(np.dot(normalized(a), normalized(b)))
