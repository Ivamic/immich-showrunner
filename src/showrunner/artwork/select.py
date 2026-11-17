# SPDX-License-Identifier: AGPL-3.0-or-later
"""Choosing frames for a picture: the best ones, unlike each other, from different videos.

Every frame of a video is looked at once: its quality, its faces, where to crop it and a tiny
copy to compare it with others. That look is kept (by asset and checksum), the pixels are
not: a chosen frame is fetched again by its time when a picture is drawn.

The choice is greedy: the best frame first, then each next one the best of the rest after a
penalty for looking like one already taken and for coming from a video already used. A seed
other than 0 shakes the scores a little, for "other frames"."""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from PIL import Image

from showrunner.artwork.faces import Face, FaceDetector
from showrunner.artwork.focus import focus
from showrunner.artwork.paint import Frame
from showrunner.artwork.quality import Quality, assess

LOOK_VERSION = 1
"""Raised when the way frames are looked at changes, so kept looks are made again."""
SIGNATURE_SIDE = 12
FACE_BONUS = 0.12
FACE_SIZE_BONUS = 0.5
"""Bonus for faces grows with their size, up to this much more."""
LIKENESS_PENALTY = 0.6
SAME_VIDEO_PENALTY = 0.08
TOO_ALIKE = 0.94
"""Frames this alike count as the same picture."""
POOR = 0.2
"""Frames scoring below this are taken only when nothing better is left."""
SHAKE = 0.12


@dataclass(frozen=True)
class FrameLook:
    """What is kept about a frame of a video."""

    asset_id: str
    at: float
    quality: Quality
    faces: tuple[Face, ...]
    point: tuple[float, float]
    region: tuple[float, float, float, float] | None
    signature: tuple[int, ...] = field(repr=False)
    """A tiny colour copy, to tell alike frames."""

    @property
    def score(self) -> float:
        if not self.faces:
            return self.quality.score
        largest = max(face.box[2] * face.box[3] for face in self.faces)
        return self.quality.score + FACE_BONUS * (1 + FACE_SIZE_BONUS * min(1.0, largest / 0.05))

    def frame(self, image: Image.Image) -> Frame:
        return Frame(image=image, focus=self.point, region=self.region)

    def to_dict(self) -> dict[str, Any]:
        return {
            "v": LOOK_VERSION,
            "asset_id": self.asset_id,
            "at": self.at,
            "quality": self.quality.to_dict(),
            "faces": [
                {"box": [round(v, 4) for v in f.box], "score": round(f.score, 3)}
                for f in self.faces
            ],
            "point": [round(v, 4) for v in self.point],
            "region": [round(v, 4) for v in self.region] if self.region else None,
            "signature": list(self.signature),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FrameLook | None:
        """None for a look made by another version: it is to be made again."""
        if data.get("v") != LOOK_VERSION:
            return None
        return cls(
            asset_id=data["asset_id"],
            at=float(data["at"]),
            quality=Quality(**data["quality"]),
            faces=tuple(Face(box=tuple(f["box"]), score=f["score"]) for f in data["faces"]),
            point=(data["point"][0], data["point"][1]),
            region=tuple(data["region"]) if data["region"] else None,
            signature=tuple(data["signature"]),
        )


def look(asset_id: str, at: float, image: Image.Image, detector: FaceDetector) -> FrameLook:
    """Look at one frame. Blocking: run it in a worker thread."""
    faces = tuple(detector.detect(image))
    where = focus(image, faces)
    return FrameLook(
        asset_id=asset_id,
        at=at,
        quality=assess(image),
        faces=faces,
        point=where.point,
        region=where.region,
        signature=signature(image),
    )


def signature(image: Image.Image) -> tuple[int, ...]:
    tiny = image.convert("RGB").resize((SIGNATURE_SIDE, SIGNATURE_SIDE), Image.Resampling.BOX)
    return tuple(int(v) for v in np.asarray(tiny).reshape(-1))


def likeness(a: FrameLook, b: FrameLook) -> float:
    """1 for the same picture, towards 0 for very different ones."""
    x = np.asarray(a.signature, dtype=np.float32)
    y = np.asarray(b.signature, dtype=np.float32)
    # Compare the layout of light and colour, not the overall brightness.
    x -= x.mean()
    y -= y.mean()
    return float(1 - np.abs(x - y).mean() / 128)


def choose(looks: Sequence[FrameLook], count: int, seed: int = 0) -> list[FrameLook]:
    """Up to `count` frames, the best first."""
    rng = random.Random(seed)
    shaken = {
        id(item): item.score + (rng.uniform(0, SHAKE) if seed else 0.0)
        for item in sorted(looks, key=lambda item: (item.asset_id, item.at))
    }
    left = sorted(looks, key=lambda item: (-shaken[id(item)], item.asset_id, item.at))
    chosen: list[FrameLook] = []
    while left and len(chosen) < count:
        best: tuple[float, FrameLook] | None = None
        for item in left:
            alike = max((likeness(item, other) for other in chosen), default=0.0)
            if alike >= TOO_ALIKE:
                continue
            same_video = sum(1 for other in chosen if other.asset_id == item.asset_id)
            value = shaken[id(item)] - LIKENESS_PENALTY * max(0.0, alike - 0.5) * 2
            value -= SAME_VIDEO_PENALTY * same_video
            if item.score < POOR:
                value -= 1
            if best is None or value > best[0]:
                best = (value, item)
        if best is None:
            break
        chosen.append(best[1])
        left.remove(best[1])
    return chosen
