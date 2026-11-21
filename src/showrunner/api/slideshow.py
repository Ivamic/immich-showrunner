# SPDX-License-Identifier: AGPL-3.0-or-later
"""Slideshows on the page (D-103): the settings, the slideshows of an album and what the user
chose for them, a look at a slideshow drawn, and the music: the set and the user's own pieces.

A change is saved and the full pass it asks for plans and draws the slideshows, as for every
other edit. Only files the app wrote are ever served: a slideshow it drew, a piece of music in
its data folder."""

import json
import os
import re
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

import yaml
from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from showrunner.api.auth import CurrentUser, DbDep, SettingsDep
from showrunner.api.errors import ApiError
from showrunner.api.shows import AlbumsDep, row_for, state_of
from showrunner.artwork.worker import music_task, render_worker
from showrunner.config import Settings
from showrunner.model.naming import kodi_special_file_stem, safe_name, special_file_stem
from showrunner.slideshow.library import (
    AUDIO,
    Piece,
    kept,
    own_pieces,
    remember,
    set_manifest,
    set_pieces,
)
from showrunner.slideshow.music import MAX_BYTES, MusicAnalysis, MusicError
from showrunner.store.models import FileRow
from showrunner.store.registry import Registry
from showrunner.targets.base import JELLYFIN, KODI, SLIDESHOWS, FileKind

router = APIRouter()

Mood = Literal["calm", "wistful", "bright", "upbeat", "solemn"]


# --- settings ---------------------------------------------------------------------------------


class SettingsOut(BaseModel):
    enabled: bool
    credits: bool
    folder: bool
    """A folder of slideshows is set: the output folders link to it (D-102)."""
    data: bool
    """The data folder is there: without it nothing can be drawn."""


class SettingsIn(BaseModel):
    enabled: bool | None = None
    credits: bool | None = None


async def _settings(db: DbDep, settings: Settings) -> SettingsOut:
    row = await Registry(db).slideshow_setting()
    return SettingsOut(
        enabled=settings.slideshow or (row is not None and row.enabled),
        credits=row.credits if row is not None else settings.slideshow_credits,
        folder=settings.slideshow_dir is not None,
        data=settings.data_dir is not None,
    )


@router.get("/slideshow/settings")
async def get_settings(user: CurrentUser, db: DbDep, settings: SettingsDep) -> SettingsOut:
    return await _settings(db, settings)


@router.put("/slideshow/settings")
async def put_settings(
    body: SettingsIn, request: Request, user: CurrentUser, db: DbDep, settings: SettingsDep
) -> SettingsOut:
    values = {k: v for k, v in body.model_dump().items() if v is not None}
    if values:
        registry = Registry(db)
        current = await registry.slideshow_setting()
        base = {
            "enabled": current.enabled if current is not None else False,
            "credits": current.credits if current is not None else settings.slideshow_credits,
        }
        await registry.save_slideshow_setting(**(base | values))
        await registry.commit()
        state_of(request).request()
    return await _settings(db, settings)


# --- the slideshows of an album ---------------------------------------------------------------


class SlideshowOut(BaseModel):
    year: int
    part: int
    title: str
    seconds: float
    photos: int
    left_out: int
    music: list[str]
    state: Literal["drawn", "older", "waiting"]
    """Drawn as planned; an older one shown while this one waits; none yet."""
    report: dict[str, Any] = {}
    """Why photos were left out: `reasons` (junk, series, poor, scene), `scenes`, `days` (each
    with its photos, shown and reasons), `not_looked` (photos of the year not looked at yet)."""


class AlbumSlideshowOut(BaseModel):
    enabled: bool | None
    """False: switched off for this album; None: as the settings say."""
    mood: Mood | None
    auto_mood: Mood | None
    slideshows: list[SlideshowOut]


class AlbumSlideshowIn(BaseModel):
    enabled: bool | None = None
    mood: Mood | None = None
    other_music: bool = False


async def _video_rows(db: DbDep, album_id: UUID) -> list[FileRow]:
    rows = await db.scalars(
        select(FileRow).where(FileRow.album_id == album_id, FileRow.kind == FileKind.VIDEO.value)
    )
    return list(rows)


def _row_of(rows: list[FileRow], year: int, part: int) -> FileRow | None:
    """The file of a slideshow: in the folder of slideshows first, else in an output folder."""
    names = (special_file_stem(year, part), kodi_special_file_stem(year, part))
    found = [r for r in rows if Path(r.path).stem in names]
    order = {SLIDESHOWS: 0, JELLYFIN: 1, KODI: 2}
    return min(found, key=lambda r: order.get(r.target, 3), default=None)


@router.get("/shows/{album_id}/slideshow")
async def album_slideshow(
    album_id: UUID, user: CurrentUser, db: DbDep, albums: AlbumsDep
) -> AlbumSlideshowOut:
    registry = Registry(db)
    await row_for(registry, albums, album_id)
    choice = (await registry.album_slideshows()).get(album_id)
    rows = await _video_rows(db, album_id)
    slideshows = []
    for planned in choice.planned if choice is not None else []:
        row = _row_of(rows, planned["year"], planned["part"])
        state: Literal["drawn", "older", "waiting"] = (
            "waiting"
            if row is None
            else "drawn"
            if row.source_version == planned["version"]
            else "older"
        )
        slideshows.append(
            SlideshowOut(
                year=planned["year"],
                part=planned["part"],
                title=planned["title"],
                seconds=planned["seconds"],
                photos=planned["photos"],
                left_out=planned["left_out"],
                music=planned["music"],
                state=state,
                report=planned.get("report", {}),
            )
        )
    return AlbumSlideshowOut(
        enabled=choice.enabled if choice is not None else None,
        mood=choice.mood if choice is not None else None,
        auto_mood=choice.auto_mood if choice is not None else None,
        slideshows=slideshows,
    )


@router.put("/shows/{album_id}/slideshow")
async def choose(
    album_id: UUID,
    body: AlbumSlideshowIn,
    request: Request,
    user: CurrentUser,
    db: DbDep,
    albums: AlbumsDep,
) -> AlbumSlideshowOut:
    """Keep a choice; the next pass plans and draws it. A field left out stays as it was;
    `null` gives `enabled` and `mood` back to the settings and the photos."""
    registry = Registry(db)
    await row_for(registry, albums, album_id)
    current = (await registry.album_slideshows()).get(album_id)
    values: dict[str, object] = {}
    sent = body.model_fields_set
    if "enabled" in sent:
        values["enabled"] = False if body.enabled is False else None
    if "mood" in sent:
        values["mood"] = body.mood
    if body.other_music:
        values["music_seed"] = (current.music_seed if current is not None else 0) + 1
    if values:
        await registry.save_album_slideshow(album_id, **values)
        await registry.commit()
        state_of(request).request()
    return await album_slideshow(album_id, user, db, albums)


@router.get("/shows/{album_id}/slideshow/video")
async def video(
    album_id: UUID,
    year: int,
    part: int,
    user: CurrentUser,
    db: DbDep,
    settings: SettingsDep,
    download: bool = False,
) -> FileResponse:
    """A slideshow the app drew for the album, to watch or (`download`) to save under the name
    of the show and the slideshow; nothing else is served."""
    row = _row_of(await _video_rows(db, album_id), year, part)
    folders = {
        SLIDESHOWS: settings.slideshow_dir,
        JELLYFIN: settings.jellyfin_dir,
        KODI: settings.kodi_output_dir,
    }
    folder = folders.get(row.target) if row is not None else None
    if row is None or folder is None:
        raise ApiError(404, "slideshow_not_found")
    file = (folder / row.path).resolve()
    if not file.is_relative_to(folder.resolve()) or not file.is_file():
        raise ApiError(404, "slideshow_not_found")
    if not download:
        return FileResponse(file, media_type="video/mp4")
    show = (await Registry(db).shows()).get(album_id)
    choice = (await Registry(db).album_slideshows()).get(album_id)
    planned = next(
        (
            p
            for p in (choice.planned if choice is not None else [])
            if (p["year"], p["part"]) == (year, part)
        ),
        None,
    )
    title = planned["title"] if planned else f"Photos {year}"
    # The title given on the page, or the name of the folder without its id.
    show_title = (
        (show.title or re.sub(r"\s*\[imm-[0-9a-f]+\]$", "", show.folder_name))
        if show is not None
        else ""
    )
    name = safe_name(f"{show_title} - {title}.mp4" if show_title else f"{title}.mp4")
    return FileResponse(file, media_type="video/mp4", filename=name)


class ProgressOut(BaseModel):
    """The slideshow being drawn now."""

    album_id: UUID | None
    show: str
    title: str
    started: datetime
    queue: int
    """Slideshows waiting after this one in the pass."""
    percent: int | None
    """None while the photos are fetched."""


STALE_SECONDS = 600
"""A note older than this is left over from a pass that stopped."""


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


@router.get("/slideshow/progress")
async def progress(user: CurrentUser, settings: SettingsDep) -> ProgressOut | None:
    """What is being drawn now and how far, or null when nothing is."""
    if settings.data_dir is None:
        return None
    work = settings.data_dir / "slideshows"
    note = _read_json(work / "progress.json")
    if note is None:
        return None
    frames_file = work / "frames.json"
    times = [p.stat().st_mtime for p in (work / "progress.json", frames_file) if p.exists()]
    if not times or datetime.now(UTC).timestamp() - max(times) > STALE_SECONDS:
        return None
    frames = _read_json(frames_file) or {}
    total = frames.get("total") or 0
    percent = min(100, int(100 * frames.get("frames", 0) / total)) if total else None
    try:
        return ProgressOut(**note, percent=percent)
    except ValueError:
        return None


class TrashOut(BaseModel):
    name: str
    size: int
    put_at: datetime
    """When it was put in the trash."""
    leaves_at: datetime
    """When the trash lets it go."""


def _trash_of(settings: Settings, folder: str) -> Path | None:
    """The folder of an album in the trash of slideshows (D-105)."""
    if settings.slideshow_dir is not None:
        return settings.slideshow_dir / ".trash" / folder
    if settings.data_dir is not None:
        return settings.data_dir / "trash" / folder
    return None


async def _show_folder(db: DbDep, album_id: UUID) -> str:
    show = (await Registry(db).shows()).get(album_id)
    if show is None:
        raise ApiError(404, "show_not_found")
    return show.folder_name


@router.get("/shows/{album_id}/slideshow/trash")
async def trash(
    album_id: UUID, user: CurrentUser, db: DbDep, settings: SettingsDep
) -> list[TrashOut]:
    """The slideshows of the album drawn before, kept in the trash for a while."""
    folder = _trash_of(settings, await _show_folder(db, album_id))
    if folder is None or not folder.is_dir():
        return []
    days = timedelta(days=settings.slideshow_trash_days)
    result = []
    for path in sorted(folder.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if path.is_symlink() or not path.is_file():
            continue
        put = datetime.fromtimestamp(path.stat().st_mtime, UTC)
        result.append(
            TrashOut(name=path.name, size=path.stat().st_size, put_at=put, leaves_at=put + days)
        )
    return result


@router.get("/shows/{album_id}/slideshow/trash/file")
async def trash_file(
    album_id: UUID, name: str, user: CurrentUser, db: DbDep, settings: SettingsDep
) -> FileResponse:
    """A slideshow from the trash of the album, to save."""
    folder = _trash_of(settings, await _show_folder(db, album_id))
    if folder is None or "/" in name or "\\" in name or name.startswith("."):
        raise ApiError(404, "slideshow_not_found")
    file = (folder / name).resolve()
    if not file.is_relative_to(folder.resolve()) or not file.is_file():
        raise ApiError(404, "slideshow_not_found")
    return FileResponse(file, media_type="video/mp4", filename=name)


# --- music ------------------------------------------------------------------------------------


class TrackOut(BaseModel):
    id: str
    kind: Literal["set", "own"]
    title: str
    author: str
    license: str
    link: str
    mood: str
    """The mood given (by the set or the user), or the one its sound suggests."""
    mood_given: bool
    sound_mood: str
    """The mood its sound suggests (empty until it is looked at)."""
    seconds: float | None
    enabled: bool
    present: bool
    """A piece of the set is downloaded on first use: until then it can not be heard."""
    error: str | None = None
    """Why the piece is no music for slideshows."""
    file_name: str = ""


class TrackPatch(BaseModel):
    enabled: bool | None = None
    mood: Mood | None = None
    """Own pieces only; `null` lets their sound decide."""
    title: str | None = Field(default=None, max_length=300)
    author: str | None = Field(default=None, max_length=300)
    license: str | None = Field(default=None, max_length=300)
    link: str | None = Field(default=None, max_length=1000)


def _data_dir(settings: Settings) -> Path:
    if settings.data_dir is None:
        raise ApiError(409, "no_data_dir")
    return settings.data_dir


def _cache(data: Path) -> Path:
    return data / "music" / ".analysis"


def _own(data: Path) -> Path:
    return data / "music" / "own"


def _track(piece: Piece, kind: Literal["set", "own"], data: Path, off: set[str]) -> TrackOut:
    found = kept(piece, _cache(data)) if piece.path.is_file() else None
    analysis = found if isinstance(found, MusicAnalysis) else None
    return TrackOut(
        id=piece.id,
        kind=kind,
        title=piece.title or (piece.path.stem if kind == "own" else ""),
        author=piece.author,
        license=piece.licence,
        link=piece.link,
        mood=piece.mood or (analysis.mood if analysis is not None else ""),
        mood_given=bool(piece.mood),
        sound_mood=analysis.mood if analysis is not None else "",
        seconds=round(analysis.end - analysis.start, 1) if analysis is not None else None,
        enabled=piece.id not in off,
        present=piece.path.is_file(),
        error=found if isinstance(found, str) else None,
        file_name=piece.path.name if kind == "own" else "",
    )


def _set_listed(data: Path) -> list[Piece]:
    """Every piece of the set, downloaded or not."""
    present = {p.id: p for p in set_pieces(data)}
    listed = []
    for entry in set_manifest().get("tracks", []):
        piece_id = f"set/{entry['id']}"
        listed.append(
            present.get(piece_id)
            or Piece(
                id=piece_id,
                path=data / "music" / "set" / entry["file"],
                sha256=entry["sha256"],
                title=entry["title"],
                author=entry["author"],
                licence=entry["license"],
                mood=entry["mood"],
            )
        )
    return listed


@router.get("/music")
async def music(user: CurrentUser, db: DbDep, settings: SettingsDep) -> list[TrackOut]:
    data = _data_dir(settings)
    off = await Registry(db).disabled_music()
    return [_track(p, "set", data, off) for p in _set_listed(data)] + [
        _track(p, "own", data, off) for p in own_pieces(data)
    ]


def _find(data: Path, track_id: str) -> tuple[Piece, Literal["set", "own"]]:
    for piece in own_pieces(data):
        if piece.id == track_id:
            return piece, "own"
    for piece in _set_listed(data):
        if piece.id == track_id:
            return piece, "set"
    raise ApiError(404, "music_not_found")


@router.patch("/music/{track_id:path}")
async def change_track(
    track_id: str,
    body: TrackPatch,
    request: Request,
    user: CurrentUser,
    db: DbDep,
    settings: SettingsDep,
) -> TrackOut:
    """Switch a piece on or off; for an own piece, also what is known of it (written to its
    `<name>.yaml`, D-089)."""
    data = _data_dir(settings)
    piece, kind = _find(data, track_id)
    registry = Registry(db)
    sent = body.model_fields_set
    if "enabled" in sent and body.enabled is not None:
        await registry.set_music_enabled(piece.id, body.enabled)
    fields = {"title", "author", "license", "link", "mood"} & sent
    if fields and kind != "own":
        raise ApiError(400, "music_set_fixed")
    if fields:
        side = piece.path.with_suffix(".yaml")
        try:
            current = yaml.safe_load(side.read_text(encoding="utf-8")) if side.is_file() else {}
        except (OSError, yaml.YAMLError):
            current = {}
        if not isinstance(current, dict):
            current = {}
        for name in fields:
            value = getattr(body, name)
            if value:
                current[name] = value
            else:
                current.pop(name, None)
        side.write_text(yaml.safe_dump(current, allow_unicode=True), encoding="utf-8")
    await registry.commit()
    state_of(request).request()
    piece, kind = _find(data, track_id)
    return _track(piece, kind, data, await registry.disabled_music())


@router.put("/music/own/{name}")
async def upload(
    name: str, request: Request, user: CurrentUser, db: DbDep, settings: SettingsDep
) -> TrackOut:
    """Add a piece of the user's own: the body of the request is the file. It is looked at at
    once; a file that is no music for slideshows is not kept, and the reason is given."""
    data = _data_dir(settings)
    clean = safe_name(os.path.basename(name), max_bytes=150)
    if not clean or Path(clean).suffix.lower() not in AUDIO or clean.startswith("."):
        raise ApiError(400, "music_file_type")
    folder = _own(data)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / clean
    if target.exists():
        raise ApiError(409, "music_exists")
    partial = folder / f".upload-{secrets.token_hex(6)}"
    size = 0
    try:
        with partial.open("wb") as out:
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_BYTES:
                    raise ApiError(413, "music_too_large", megabytes=MAX_BYTES >> 20)
                out.write(chunk)
        try:
            found = await render_worker().run(music_task, str(partial))
        except MusicError as exc:
            raise ApiError(400, "music_not_usable", reason=str(exc)) from exc
        os.replace(partial, target)
    finally:
        partial.unlink(missing_ok=True)
    piece, _ = _find(data, next(p.id for p in own_pieces(data) if p.path == target))
    analysis = MusicAnalysis.from_dict(found)
    if analysis is not None:
        remember(piece, _cache(data), analysis)
    state_of(request).request()
    return _track(piece, "own", data, await Registry(db).disabled_music())


@router.delete("/music/{track_id:path}")
async def remove(
    track_id: str, request: Request, user: CurrentUser, settings: SettingsDep
) -> dict[str, bool]:
    """Remove a piece of the user's own (and its `<name>.yaml`); the set stays."""
    data = _data_dir(settings)
    piece, kind = _find(data, track_id)
    if kind != "own":
        raise ApiError(400, "music_set_fixed")
    piece.path.unlink(missing_ok=True)
    piece.path.with_suffix(".yaml").unlink(missing_ok=True)
    state_of(request).request()
    return {"removed": True}


AUDIO_TYPES = {
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".ogg": "audio/ogg",
    ".oga": "audio/ogg",
    ".opus": "audio/ogg",
    ".flac": "audio/flac",
    ".wav": "audio/wav",
}


@router.get("/music/file/{track_id:path}")
async def music_file(track_id: str, user: CurrentUser, settings: SettingsDep) -> FileResponse:
    """A piece of music in the data folder of the app, to listen to on the page."""
    data = _data_dir(settings)
    piece, _ = _find(data, track_id)
    file = piece.path.resolve()
    if not file.is_relative_to((data / "music").resolve()) or not file.is_file():
        raise ApiError(404, "music_not_found")
    return FileResponse(file, media_type=AUDIO_TYPES.get(file.suffix.lower(), "audio/mpeg"))
