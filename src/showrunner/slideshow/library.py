# SPDX-License-Identifier: AGPL-3.0-or-later
"""The music slideshows may use: the music set of the app and the user's own pieces.

The set (D-088, D-089) is described by `music_set.json` in the package: each piece with its
file, SHA-256, author, licence (CC0, public domain or CC BY only) and mood. The files are not in
the image: they come as one archive from the project's own mirror, downloaded on first use into
the data folder and kept only when every piece is the one described.

The user's own pieces lie in `<data>/music/own/`. Next to a piece an optional `<name>.yaml` may
give its title, author, licence, link and mood; what it leaves out is taken from the tags of the
file, and what is still unknown is simply not shown (D-089). Nothing is checked or forbidden: the
rights to one's own music are one's own.

Each piece is looked at once (`music.analyse`, in the worker); the analysis is kept next to the
music, by the SHA-256 of the file."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import av
import httpx2
import yaml

from showrunner.slideshow.music import ANALYSIS_VERSION, MusicAnalysis, MusicError
from showrunner.slideshow.score import Track

log = logging.getLogger(__name__)

SET_MANIFEST = Path(__file__).parent / "music_set.json"
AUDIO = (".mp3", ".m4a", ".aac", ".ogg", ".oga", ".opus", ".flac", ".wav")
MOODS = ("calm", "wistful", "bright", "upbeat", "solemn", "cinematic")
"""D-100: by energy and colour; wistful (slow and sad) is never chosen for an album on its own.
Cinematic (D-110): wide and slow-building, as over a landscape seen from above."""
ENERGIES = ("low", "medium", "high")
COLOURS = ("sad", "neutral", "bright", "grand")
SET_LICENCES = ("CC0 1.0", "Public Domain Mark 1.0", "CC BY 3.0", "CC BY 3.0 US", "CC BY 4.0")


@dataclass(frozen=True)
class Piece:
    """A piece of music before it is looked at."""

    id: str
    path: Path
    sha256: str
    title: str = ""
    author: str = ""
    licence: str = ""
    link: str = ""
    mood: str = ""
    changed: bool = True
    """Cut and faded by the app: the credit says so (CC BY asks for it)."""

    @property
    def credit(self) -> str:
        """One line for the credits and the description; empty when nothing is known."""
        name = f"“{self.title}”" if self.title else ""
        who = f"by {self.author}" if self.author else ""
        parts = [" ".join(p for p in (name, who) if p)]
        if self.licence:
            parts.append(self.licence)
        if self.link:
            parts.append(self.link)
        line = ", ".join(p for p in parts if p)
        if line and self.changed:
            line += "; trimmed and faded"
        return line


# --- the set ----------------------------------------------------------------------------------


def set_manifest() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(SET_MANIFEST.read_text(encoding="utf-8"))
    for entry in data.get("tracks", []):
        if entry["license"] not in SET_LICENCES:
            raise ValueError(f"the set may not hold {entry['license']} ({entry['id']})")
        if entry["mood"] not in MOODS:
            raise ValueError(f"unknown mood {entry['mood']!r} ({entry['id']})")
        if (
            entry.get("energy", "low") not in ENERGIES
            or entry.get("colour", "neutral") not in COLOURS
        ):
            raise ValueError(f"unknown energy or colour ({entry['id']})")
    return data


def set_pieces(data_dir: Path) -> list[Piece]:
    """The pieces of the set that are in the data folder and are what the manifest says."""
    manifest = set_manifest()
    folder = data_dir / "music" / "set"
    result = []
    for entry in manifest.get("tracks", []):
        path = folder / entry["file"]
        if not path.is_file() or _sha256(path) != entry["sha256"]:
            continue
        result.append(
            Piece(
                id=f"set/{entry['id']}",
                path=path,
                sha256=entry["sha256"],
                title=entry["title"],
                author=entry["author"],
                licence=entry["license"],
                # CC BY asks for a link to the licence; the source is in THIRD_PARTY_NOTICES.md.
                link=entry.get("license_url", "") if entry["license"].startswith("CC BY") else "",
                mood=entry["mood"],
                # Public domain and CC0 ask for nothing; the line is kept as a courtesy.
                changed=entry["license"].startswith("CC BY"),
            )
        )
    return result


async def ensure_set(data_dir: Path, *, transport: httpx2.AsyncBaseTransport | None = None) -> int:
    """Download the music set when pieces of it are missing; the number of pieces there after.
    Without a network the slideshows go without the set (and a line in the log)."""
    manifest = set_manifest()
    tracks = manifest.get("tracks", [])
    archive = manifest.get("archive")
    if not tracks or not archive:
        return 0
    have = len(set_pieces(data_dir))
    if have == len(tracks):
        return have
    folder = data_dir / "music" / "set"
    folder.mkdir(parents=True, exist_ok=True)
    partial = folder / ".set.zip.part"
    try:
        digest = hashlib.sha256()
        async with (
            httpx2.AsyncClient(
                transport=transport, follow_redirects=True, timeout=httpx2.Timeout(60.0)
            ) as client,
            client.stream("GET", archive["url"]) as response,
        ):
            response.raise_for_status()
            with partial.open("wb") as out:
                async for chunk in response.aiter_bytes(1 << 20):
                    digest.update(chunk)
                    out.write(chunk)
        if digest.hexdigest() != archive["sha256"]:
            raise ValueError("the archive is not the music set")
        wanted = {entry["file"] for entry in tracks}
        with zipfile.ZipFile(partial) as zipped:
            for name in zipped.namelist():
                base = os.path.basename(name)
                if base not in wanted:
                    continue  # nothing but the pieces, and never outside the folder
                target = folder / base
                with zipped.open(name) as source, (folder / f".{base}.part").open("wb") as out:
                    out.write(source.read())
                os.replace(folder / f".{base}.part", target)
    except (httpx2.HTTPError, OSError, ValueError, zipfile.BadZipFile) as exc:
        log.warning("the music set could not be downloaded, slideshows go without it: %s", exc)
    finally:
        partial.unlink(missing_ok=True)
    return len(set_pieces(data_dir))


# --- the user's own ---------------------------------------------------------------------------


def own_pieces(data_dir: Path) -> list[Piece]:
    folder = data_dir / "music" / "own"
    if not folder.is_dir():
        return []
    result = []
    for path in sorted(folder.iterdir()):
        if not path.is_file() or path.suffix.lower() not in AUDIO or path.name.startswith("."):
            continue
        fields = {**_tags(path), **_sidecar(path)}
        sha = _sha256(path)
        mood = str(fields.get("mood", "")).strip().lower()
        result.append(
            Piece(
                id=f"own/{path.name}@{sha[:12]}",
                path=path,
                sha256=sha,
                title=str(fields.get("title", "")).strip(),
                author=str(fields.get("author", "")).strip(),
                licence=str(fields.get("license", "")).strip(),
                link=str(fields.get("link", "")).strip(),
                mood=mood if mood in MOODS else "",
            )
        )
    return result


def _sidecar(path: Path) -> dict[str, Any]:
    """`<name>.yaml` next to a piece; unreadable or missing is the same as empty."""
    side = path.with_suffix(".yaml")
    if not side.is_file():
        return {}
    try:
        data = yaml.safe_load(side.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        log.warning("%s could not be read, it is left out: %s", side.name, exc)
        return {}
    if not isinstance(data, dict):
        return {}
    known = ("title", "author", "license", "link", "mood")
    return {k: v for k, v in data.items() if k in known and isinstance(v, str | int | float)}


def _tags(path: Path) -> dict[str, str]:
    """Title, artist, licence or copyright, and a link, from the tags of the file."""
    try:
        with av.open(str(path)) as file:
            tags = {k.lower(): v for k, v in file.metadata.items()}
            if file.streams.audio:
                tags.update({k.lower(): v for k, v in file.streams.audio[0].metadata.items()})
    except (av.error.FFmpegError, OSError):
        return {}
    result = {}
    if tags.get("title"):
        result["title"] = tags["title"]
    artist = tags.get("artist") or tags.get("album_artist") or tags.get("composer")
    if artist:
        result["author"] = artist
    licence = tags.get("license") or tags.get("copyright")
    if licence:
        result["license"] = licence
    link = tags.get("www") or tags.get("url") or tags.get("contact")
    if link:
        result["link"] = link
    return result


# --- looked at --------------------------------------------------------------------------------


def pending(pieces: Iterable[Piece], cache: Path) -> list[Piece]:
    """The pieces not looked at yet by this version."""
    return [p for p in pieces if kept(p, cache) is None]


def remember(piece: Piece, cache: Path, found: MusicAnalysis | MusicError) -> None:
    """Keep what was learned about a piece: its analysis, or why it is no music for slideshows
    (it is then left out until the way music is looked at changes)."""
    cache.mkdir(parents=True, exist_ok=True)
    if isinstance(found, MusicError):
        log.warning("%s is left out of slideshows: %s", piece.path.name, found)
        record: dict[str, Any] = {"v": ANALYSIS_VERSION, "error": str(found)}
    else:
        record = found.to_dict()
    (cache / f"{piece.sha256}.json").write_text(json.dumps(record), encoding="utf-8")


def tracks(pieces: Iterable[Piece], cache: Path) -> list[Track]:
    """The pieces looked at and fit for slideshows, as the music of slideshows."""
    result = []
    for piece in pieces:
        found = kept(piece, cache)
        if isinstance(found, MusicAnalysis):
            result.append(Track(piece.id, found, piece.credit, piece.mood or found.mood))
    return result


def kept(piece: Piece, cache: Path) -> MusicAnalysis | str | None:
    """The kept analysis of a piece, the reason it is left out, or None when it is to be
    looked at (again)."""
    path = cache / f"{piece.sha256}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if data.get("v") != ANALYSIS_VERSION:
        return None
    if data.get("error"):
        return str(data["error"])
    return MusicAnalysis.from_dict(data)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "Piece",
    "ensure_set",
    "own_pieces",
    "pending",
    "remember",
    "set_manifest",
    "set_pieces",
    "tracks",
]
