# SPDX-License-Identifier: AGPL-3.0-or-later
"""What to keep in view when a frame is cropped to a cell.

With faces, the region to keep is the box around them (with room above the heads and some
margin), and the focus is their middle, larger faces weighing more. Without faces, the focus
is the middle of what draws the eye, in the spirit of smartcrop: edges, saturated color and
skin tones, a little drawn towards the center of the frame."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image

from showrunner.artwork.faces import Face

WORK_SIDE = 160
CENTER_PULL = 0.35
"""How much more what draws the eye counts in the middle of the frame than at its edge."""


@dataclass(frozen=True)
class Focus:
    point: tuple[float, float]
    """Shares of width and height; stays in view and as near the middle of the crop as it can."""
    region: tuple[float, float, float, float] | None = None
    """x, y, width, height as shares: kept whole in the crop when it fits."""


def focus(image: Image.Image, faces: Sequence[Face]) -> Focus:
    if faces:
        return _faces_focus(faces)
    return Focus(point=salient_point(image))


def _faces_focus(faces: Sequence[Face]) -> Focus:
    # Only faces that matter next to the largest one: a passer-by far behind does not.
    largest = max(face.area for face in faces)
    kept = [face for face in faces if face.area >= largest * 0.15]
    weight = sum(face.area * face.score for face in kept)
    cx = sum(face.center[0] * face.area * face.score for face in kept) / weight
    cy = sum(face.center[1] * face.area * face.score for face in kept) / weight
    x0 = min(face.box[0] for face in kept)
    y0 = min(face.box[1] for face in kept)
    x1 = max(face.box[0] + face.box[2] for face in kept)
    y1 = max(face.box[1] + face.box[3] for face in kept)
    unit = max(face.box[3] for face in kept)
    # Room above the head and around the faces, a little more below (shoulders).
    x0, x1 = x0 - unit * 0.35, x1 + unit * 0.35
    y0, y1 = y0 - unit * 0.45, y1 + unit * 0.6
    region = (max(0.0, x0), max(0.0, y0), min(1.0, x1) - max(0.0, x0), min(1.0, y1) - max(0.0, y0))
    return Focus(point=(cx, cy), region=region)


def salient_point(image: Image.Image) -> tuple[float, float]:
    small = image.convert("RGB")
    small.thumbnail((WORK_SIDE, WORK_SIDE), Image.Resampling.BILINEAR)
    rgb = np.asarray(small)
    grey = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
    edges = cv2.magnitude(cv2.Sobel(grey, cv2.CV_32F, 1, 0), cv2.Sobel(grey, cv2.CV_32F, 0, 1))
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    saturation = hsv[..., 1].astype(np.float32) / 255 * (hsv[..., 2].astype(np.float32) / 255)
    ycrcb = cv2.cvtColor(rgb, cv2.COLOR_RGB2YCrCb)
    skin = (
        (ycrcb[..., 1] > 135) & (ycrcb[..., 1] < 175) & (ycrcb[..., 2] > 85) & (ycrcb[..., 2] < 130)
    ).astype(np.float32)

    def norm(values: np.ndarray) -> np.ndarray:
        top = float(values.max())
        return values / top if top > 0 else values

    interest = 0.5 * norm(edges) + 0.25 * norm(saturation) + 0.25 * skin
    interest = cv2.GaussianBlur(interest, (0, 0), max(1.0, WORK_SIDE / 40))
    height, width = interest.shape
    ys, xs = np.mgrid[0:height, 0:width].astype(np.float32)
    middle = np.exp(-(((xs / width - 0.5) / 0.35) ** 2 + ((ys / height - 0.5) / 0.35) ** 2))
    # The middle only tips the balance between interesting places; a plain middle adds nothing.
    weight = norm(interest) ** 2 * ((1 - CENTER_PULL) + CENTER_PULL * middle)
    total = float(weight.sum())
    if total <= 0:
        return 0.5, 0.5
    return float((weight * xs).sum() / total / width), float((weight * ys).sum() / total / height)
