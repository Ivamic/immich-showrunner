# SPDX-License-Identifier: AGPL-3.0-or-later
"""How good a frame is to look at: sharp, well exposed, with contrast and color, large enough.

Each measure is brought to 0..1 and the score is their weighted sum, lowered for a small
frame. A blurred frame of a moving camera, a dark one, a fade to black or a washed-out sky
scores low. Measured on a small copy, so it is quick and does not depend on the frame size."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import cv2
import numpy as np
from PIL import Image

WORK_SIDE = 512
FULL_SIZE = 1280
"""A frame this large (long side) loses nothing for its size."""
WEIGHTS = {
    "sharpness": 0.35,
    "exposure": 0.2,
    "contrast": 0.15,
    "colorfulness": 0.1,
    "unclipped": 0.2,
}


@dataclass(frozen=True)
class Quality:
    sharpness: float
    exposure: float
    contrast: float
    colorfulness: float
    clipped: float
    """Share of pixels that are pure black or pure white."""
    size: int
    """Long side of the frame in pixels."""
    score: float

    def to_dict(self) -> dict[str, float]:
        return {k: round(v, 4) if isinstance(v, float) else v for k, v in asdict(self).items()}


def assess(image: Image.Image) -> Quality:
    size = max(image.size)
    small = image.convert("RGB")
    small.thumbnail((WORK_SIDE, WORK_SIDE), Image.Resampling.BILINEAR)
    rgb = np.asarray(small, dtype=np.float32)
    grey = cv2.cvtColor(rgb.astype(np.uint8), cv2.COLOR_RGB2GRAY).astype(np.float32)

    variance = float(cv2.Laplacian(grey, cv2.CV_32F).var())
    sharpness = 1 - math.exp(-variance / 150)
    mean = float(grey.mean()) / 255
    exposure = math.exp(-(((mean - 0.48) / 0.24) ** 2))
    contrast = min(1.0, float(grey.std()) / 255 / 0.22)
    clipped = float(((grey < 4) | (grey > 251)).mean())

    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    rg, yb = r - g, 0.5 * (r + g) - b
    colorful = math.hypot(float(rg.std()), float(yb.std())) + 0.3 * math.hypot(
        float(rg.mean()), float(yb.mean())
    )
    colorfulness = min(1.0, colorful / 90)

    parts = {
        "sharpness": sharpness,
        "exposure": exposure,
        "contrast": contrast,
        "colorfulness": colorfulness,
        "unclipped": max(0.0, 1 - clipped * 2.5),
    }
    score = sum(WEIGHTS[k] * v for k, v in parts.items())
    score *= min(1.0, size / FULL_SIZE) ** 0.5
    return Quality(
        sharpness=sharpness,
        exposure=exposure,
        contrast=contrast,
        colorfulness=colorfulness,
        clipped=clipped,
        size=size,
        score=score,
    )
