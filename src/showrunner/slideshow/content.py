# SPDX-License-Identifier: AGPL-3.0-or-later
"""What a photo shows, told by its CLIP embedding against embeddings of words made beforehand
(`prompts.json`, from tools/clip_prompts.py): a screenshot, a document or a receipt is left out of
a slideshow.

The words are compared as CLIP does it: the similarities, scaled by 100, become shares by
softmax, and a photo is junk when the words of junk take most of the share."""

from __future__ import annotations

import base64
import json
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import numpy as np

from showrunner.slideshow.models import CLIP

PROMPTS = Path(__file__).parent / "prompts.json"
LOGIT_SCALE = 100.0
JUNK_SHARE = 0.7
"""A photo is junk when the words of junk take more than this share."""


@dataclass(frozen=True)
class Prompts:
    groups: tuple[str, ...]
    texts: tuple[str, ...]
    vectors: np.ndarray
    """One row per word, each of length 1."""


@cache
def prompts() -> Prompts:
    data = json.loads(PROMPTS.read_text(encoding="utf-8"))
    if data["model"] != CLIP.id:
        raise RuntimeError(f"prompts.json is made for {data['model']}, not {CLIP.id}")
    rows = [
        np.frombuffer(base64.b64decode(p["vector"]), dtype="<f2").astype(np.float32)
        for p in data["prompts"]
    ]
    return Prompts(
        groups=tuple(p["group"] for p in data["prompts"]),
        texts=tuple(p["text"] for p in data["prompts"]),
        vectors=np.stack(rows),
    )


def shares(embedding: np.ndarray) -> dict[str, float]:
    """The share of each group of words for a photo."""
    words = prompts()
    vector = embedding / max(float(np.linalg.norm(embedding)), 1e-12)
    logits = LOGIT_SCALE * (words.vectors @ vector)
    weights = np.exp(logits - logits.max())
    weights /= weights.sum()
    result: dict[str, float] = {}
    for group, weight in zip(words.groups, weights, strict=True):
        result[group] = result.get(group, 0.0) + float(weight)
    return result


def is_junk(embedding: np.ndarray) -> bool:
    """A screenshot, a document, a receipt…: not for a slideshow."""
    return shares(embedding).get("junk", 0.0) > JUNK_SHARE


def best_words(embedding: np.ndarray, count: int = 3) -> list[tuple[str, float]]:
    """The words closest to a photo, for the logs and for choosing music later."""
    words = prompts()
    vector = embedding / max(float(np.linalg.norm(embedding)), 1e-12)
    similarity = words.vectors @ vector
    order = np.argsort(-similarity)[:count]
    return [(words.texts[i], float(similarity[i])) for i in order]


WORD_MOODS: dict[str, str] = {
    "a group photo at a party": "upbeat",
    "a photo of a child": "bright",
    "a family photo": "bright",
    "a selfie": "bright",
    "a photo of people": "bright",
    "a photo of the sea and a beach": "bright",
    "a photo of a city street": "bright",
    "a photo of a building": "bright",
    "a photo of food on a table": "bright",
    "a photo of an animal": "bright",
    "a photo of a room": "bright",
    "a landscape photo": "cinematic",
    "a photo of mountains": "cinematic",
    "an aerial photo of a landscape from above": "cinematic",
    "a wide view over a valley": "cinematic",
    "a photo of flowers and plants": "calm",
    "a photo of snow in winter": "calm",
    "a photo taken at night": "calm",
    "a tourist posing in front of a landmark": "bright",
    "a person standing next to a sign": "bright",
    "a photo in a museum": "calm",
    "a photo of a person in a shop": "bright",
    "a street with shop signs": "bright",
    "a photo of ancient ruins": "calm",
}
"""What the music of a slideshow should feel like, by what its photos show."""


def album_mood(embeddings: Sequence[np.ndarray]) -> str:
    """The mood of the music for a slideshow: the words of photos each photo is closest to,
    their moods counted over all photos (a party anywhere makes it upbeat more easily)."""
    if not embeddings:
        return "calm"
    words = prompts()
    photo_rows = [i for i, g in enumerate(words.groups) if g == "photo"]
    counts: dict[str, float] = {}
    for embedding in embeddings:
        vector = embedding / max(float(np.linalg.norm(embedding)), 1e-12)
        similarity = words.vectors[photo_rows] @ vector
        best = words.texts[photo_rows[int(np.argmax(similarity))]]
        mood = WORD_MOODS.get(best, "calm")
        counts[mood] = counts.get(mood, 0.0) + (2.0 if mood == "upbeat" else 1.0)
    return max(sorted(counts), key=lambda m: counts[m])
