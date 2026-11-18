# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fitting a title into a box: the number of lines, where to break them and the size.

Every number of lines up to the limit is tried with the words balanced between the lines;
the largest size wins, with a small penalty for each extra line. A title too long for the
smallest size is cut at a word with "…", leaving no short word (a preposition) hanging
before it. A word without spaces — a file name — is broken after `_` and `-` first, then,
if still too wide, between letters with a hyphen. Widths are measured with the font."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

ELLIPSIS = "…"
LINE_PENALTY = 0.12
REFERENCE_SIZE = 100

Measure = Callable[[str, float], float]
"""Width of a line at a size, in pixels."""


@dataclass(frozen=True)
class FittedText:
    lines: tuple[str, ...]
    size: int
    truncated: bool = False


@lru_cache(maxsize=64)
def font(
    path: Path, size: int, index: int = 0, variation: str | None = None
) -> ImageFont.FreeTypeFont:
    face = ImageFont.truetype(str(path), size=size, index=index)
    if variation:
        face.set_variation_by_name(variation)
    return face


def font_measure(
    path: Path, index: int = 0, variation: str | None = None, spacing: float = 0
) -> Measure:
    """Width at any size, from the width at a reference size (the outline scales linearly).
    `spacing` is the extra space between letters in parts of the size."""
    reference = font(path, REFERENCE_SIZE, index, variation)

    def measure(text: str, size: float) -> float:
        extra = spacing * size * max(0, len(text) - 1)
        return reference.getlength(text) * size / REFERENCE_SIZE + extra

    return measure


def join(words: list[str]) -> str:
    """Words back into a line: no space after a piece that ends with `_` or `-`."""
    line = ""
    for word in words:
        line += " " + word if line and not line.endswith(("_", "-")) else word
    return line


def tokens(text: str, width: float, size: float, measure: Measure) -> list[str]:
    """Words of the text; parts of a word joined by `_` or `-` are separate words, and a part
    wider than the line at this size is broken between letters with a hyphen."""
    out: list[str] = []
    for word in _bound(text.split(), width, size, measure):
        if " " in word:
            out.append(word)
            continue
        for part in re.split(r"(?<=[_\-])", word):
            if not part:
                continue
            while measure(part, size) > width and len(part) > 1:
                cut = len(part) - 1
                while cut > 1 and measure(part[:cut] + "-", size) > width:
                    cut -= 1
                out.append(part[:cut] + "-")
                part = part[cut:]
            out.append(part)
    return out


def _short(word: str) -> bool:
    return len(word) <= 2 and word.isalpha()


def _bound(words: list[str], width: float, size: float, measure: Measure) -> list[str]:
    """A short word (a preposition, a conjunction) kept on the line of the word after it,
    when the two fit on one line."""
    out: list[str] = []
    i = 0
    while i < len(words):
        word = words[i]
        while _short(word.split(" ")[-1]) and i + 1 < len(words):
            joined = f"{word} {words[i + 1]}"
            if measure(joined, size) > width:
                break
            word = joined
            i += 1
        out.append(word)
        i += 1
    return out


def balanced(words: list[str], lines: int, measure: Measure) -> list[str]:
    """The words in about equally wide lines, at most `lines` of them."""
    if lines == 1 or len(words) < 2:
        return [join(words)]
    target = measure(join(words), REFERENCE_SIZE) / lines
    out: list[str] = []
    current: list[str] = []
    for word in words:
        longer = [*current, word]
        if current and measure(join(longer), REFERENCE_SIZE) > target and len(out) < lines - 1:
            # Break before the word, or after it when that is closer to the target.
            before = measure(join(current), REFERENCE_SIZE)
            after = measure(join(longer), REFERENCE_SIZE)
            if after - target < target - before and len(out) < lines - 2:
                out.append(join(longer))
                current = []
                continue
            out.append(join(current))
            current = [word]
        else:
            current = longer
    if current:
        out.append(join(current))
    return out


def wrapped(words: list[str], width: float, size: float, measure: Measure) -> list[str]:
    """The words greedily in lines no wider than the width."""
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        longer = [*current, word]
        if not current or measure(join(longer), size) <= width:
            current = longer
        else:
            lines.append(join(current))
            current = [word]
    if current:
        lines.append(join(current))
    return lines


def _cut(line: str, rest: str, width: float, size: float, measure: Measure) -> str:
    """The last kept line with as much of the rest as fits, cut at a word, with "…"."""
    text = f"{line} {rest}".strip()
    while text and measure(text + ELLIPSIS, size) > width:
        space = text.rfind(" ")
        text = text[:space] if space > 0 else text[:-1]
    shorter = re.sub(r"(\s\S{1,2})+$", "", text)
    text = shorter or text
    text = re.sub(r"[\s,.;:_\-\u2013\u2014]+$", "", text)
    return text + ELLIPSIS


def fit(
    text: str,
    width: float,
    min_size: float,
    max_size: float,
    max_lines: int,
    measure: Measure,
    height: float | None = None,
    line_height: float = 1.1,
) -> FittedText:
    """Lines and size for the text in a line `width` pixels wide; with `height`, the lines
    must also fit that high."""
    text = " ".join(text.split())
    if not text:
        return FittedText(lines=(), size=int(max_size))
    words = tokens(text, width, min_size, measure)
    best: tuple[float, int, list[str]] | None = None
    for count in range(1, min(max_lines, len(words)) + 1):
        lines = balanced(words, count, measure)
        longest = max(measure(line, 1) for line in lines)
        size = min(max_size, width / longest) if longest else max_size
        if height is not None:
            size = min(size, height / (line_height * (len(lines) - 1) + 1.2))
        score = size * (1 - LINE_PENALTY * (len(lines) - 1))
        if best is None or score > best[0]:
            best = (score, _whole(size, lines, width, measure), lines)
    if best is not None and best[1] >= min_size:
        return FittedText(lines=tuple(best[2]), size=best[1])
    size = int(min_size)
    lines = wrapped(words, width, size, measure)
    if len(lines) <= max_lines:
        return FittedText(lines=tuple(lines), size=size)
    kept = lines[: max_lines - 1]
    kept.append(_cut(lines[max_lines - 1], lines[max_lines], width, size, measure))
    return FittedText(lines=tuple(kept), size=size, truncated=True)


def _whole(size: float, lines: list[str], width: float, measure: Measure) -> int:
    """The size in whole pixels, made smaller if rounding made a line too wide."""
    whole = int(size)
    while whole > 1 and max(measure(line, whole) for line in lines) > width:
        whole -= 1
    return whole
