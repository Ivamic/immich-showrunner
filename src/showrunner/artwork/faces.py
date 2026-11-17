# SPDX-License-Identifier: AGPL-3.0-or-later
"""Faces in a frame, found by YuNet (OpenCV, on the CPU; the model ships with the app).

Boxes are shares of the frame's width and height, so they hold for any size of it."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

MODEL = Path(__file__).parent / "models" / "face_detection_yunet_2023mar.onnx"
WORK_SIDE = 640
THRESHOLD = 0.75
MIN_FACE = 0.02
"""Faces narrower than this share of the frame are too small to matter for a crop."""


@dataclass(frozen=True)
class Face:
    box: tuple[float, float, float, float]
    """x, y, width, height as shares of the frame."""
    score: float

    @property
    def area(self) -> float:
        return self.box[2] * self.box[3]

    @property
    def center(self) -> tuple[float, float]:
        x, y, w, h = self.box
        return x + w / 2, y + h / 2


class FaceDetector:
    """One detector for the app; calls are serialized, as an OpenCV net is not thread-safe."""

    def __init__(self, model: Path = MODEL, threshold: float = THRESHOLD) -> None:
        self._net = cv2.FaceDetectorYN.create(str(model), "", (WORK_SIDE, WORK_SIDE), threshold)
        self._lock = threading.Lock()

    def detect(self, image: Image.Image) -> list[Face]:
        small = image.convert("RGB")
        small.thumbnail((WORK_SIDE, WORK_SIDE), Image.Resampling.BILINEAR)
        width, height = small.size
        bgr = cv2.cvtColor(np.asarray(small), cv2.COLOR_RGB2BGR)
        with self._lock:
            self._net.setInputSize((width, height))
            _, found = self._net.detect(bgr)
        faces = []
        for row in found if found is not None else []:
            x, y, w, h = (float(v) for v in row[:4])
            x0, y0 = max(0.0, x), max(0.0, y)
            x1, y1 = min(float(width), x + w), min(float(height), y + h)
            if x1 <= x0 or y1 <= y0:
                continue
            face = Face(
                box=(x0 / width, y0 / height, (x1 - x0) / width, (y1 - y0) / height),
                score=float(row[-1]),
            )
            if face.box[2] >= MIN_FACE:
                faces.append(face)
        return sorted(faces, key=lambda f: (-f.area, f.box))
