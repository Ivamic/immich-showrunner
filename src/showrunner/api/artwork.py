# SPDX-License-Identifier: AGPL-3.0-or-later
"""Artwork on the page: the styles that may be chosen, the pictures of a show, a look at other
pictures before they are made, and what the user keeps (pinned pictures) or prefers (the
cover).

A change is not drawn here for good: it is saved, and the full pass it asks for draws the
pictures and tells the media servers, as for every other edit. The looks are drawn in the
worker process, so the page stays free meanwhile."""

import base64
import random
from typing import Annotated, Any, Literal
from urllib.parse import urlencode
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select

from showrunner.api.auth import CurrentUser, DbDep, ImmichFactoryDep, SettingsDep
from showrunner.api.errors import ApiError
from showrunner.api.shows import AlbumsDep, build, row_for, state_of
from showrunner.artwork.jobs import ArtworkJob, parse_slot, plan_show, slot_key
from showrunner.artwork.make import ArtworkError
from showrunner.artwork.style import OutputKind, Style
from showrunner.artwork.worker import HttpSource, preview_task, shared_worker
from showrunner.immich.client import ImmichError, can_download
from showrunner.model.show import SINGLE_SEASON
from showrunner.runner import styles as builtin_styles
from showrunner.store.models import FileRow
from showrunner.store.registry import Registry
from showrunner.sync.artwork import looks_of
from showrunner.targets.base import JELLYFIN, KODI, FileKind

router = APIRouter()

PREVIEW_KINDS = (OutputKind.SERIES_POSTER, OutputKind.LANDSCAPE, OutputKind.FANART)


def get_styles() -> dict[str, Style]:
    return builtin_styles()


StylesDep = Annotated[dict[str, Style], Depends(get_styles)]


# --- styles -----------------------------------------------------------------------------


class StyleOut(BaseModel):
    id: str
    names: dict[str, str]
    enabled: bool
    shows: int
    """Shows drawn in this style now."""


class StylePatch(BaseModel):
    enabled: bool


@router.get("/styles")
async def list_styles(user: CurrentUser, db: DbDep, styles: StylesDep) -> list[StyleOut]:
    registry = Registry(db)
    disabled = await registry.disabled_styles()
    used: dict[str, int] = {}
    for row in (await registry.artworks()).values():
        used[row.style_id] = used.get(row.style_id, 0) + 1
    return [
        StyleOut(id=s.id, names=s.spec.names, enabled=s.id not in disabled, shows=used.get(s.id, 0))
        for s in styles.values()
    ]


@router.patch("/styles/{style_id}")
async def edit_style(
    style_id: str,
    body: StylePatch,
    request: Request,
    user: CurrentUser,
    db: DbDep,
    styles: StylesDep,
) -> dict[str, bool]:
    """Switch a style on or off. Shows in a style switched off get another one on the next
    pass; their pinned pictures stay as they are."""
    if style_id not in styles:
        raise ApiError(404, "style_not_found")
    registry = Registry(db)
    if not body.enabled and set(styles) - await registry.disabled_styles() == {style_id}:
        raise ApiError(400, "style_last")
    await registry.set_style_enabled(style_id, body.enabled)
    await registry.commit()
    state_of(request).request()
    return {"saved": True}


# --- the pictures of a show -------------------------------------------------------------


class Picture(BaseModel):
    kind: OutputKind
    season: int | None
    slot: str
    """The name of the picture: `series_poster`, `season_poster:2024`…"""
    url: str
    pinned: bool


class ArtworkOut(BaseModel):
    style_id: str | None
    seed: int
    use_cover: bool
    slot_seeds: dict[str, int]
    pictures: list[Picture]
    waiting: int
    """Videos of the show still to look at: its pictures are drawn from the others for now."""
    syncing: bool
    """A pass runs or is about to: the pictures may change soon."""


def _kind_of(path: str) -> tuple[OutputKind, int | None] | None:
    """What a picture file of a show is, from its path (relative to the folder of the show)."""
    parts = path.split("/")
    name = parts[-1]
    if len(parts) == 2 and parts[0].startswith("Season ") and name == "poster.jpg":
        season = parts[0].removeprefix("Season ")
        return (OutputKind.SEASON_POSTER, int(season)) if season.isdigit() else None
    if len(parts) != 1:
        return None
    return {
        "folder.jpg": (OutputKind.SERIES_POSTER, None),
        "poster.jpg": (OutputKind.SERIES_POSTER, None),
        "landscape.jpg": (OutputKind.LANDSCAPE, None),
        "fanart.jpg": (OutputKind.FANART, None),
        "logo.png": (OutputKind.LOGO, None),
        "clearlogo.png": (OutputKind.LOGO, None),
    }.get(name)


async def _picture_rows(db: DbDep, album_id: UUID) -> tuple[str, dict[str, FileRow]]:
    """The pictures of a show as one target holds them (Jellyfin if it has them): the target,
    and its rows by the path inside the folder of the show."""
    rows = list(
        await db.scalars(
            select(FileRow).where(
                FileRow.album_id == album_id, FileRow.kind == FileKind.IMAGE.value
            )
        )
    )
    for target in (JELLYFIN, KODI):
        own = {
            r.path.split("/", 1)[1]: r
            for r in rows
            if r.target == target and "/" in r.path and _kind_of(r.path.split("/", 1)[1])
        }
        if own:
            return target, own
    return JELLYFIN, {}


@router.get("/shows/{album_id}/artwork")
async def get_artwork(
    album_id: UUID, request: Request, user: CurrentUser, db: DbDep, albums: AlbumsDep
) -> ArtworkOut:
    registry = Registry(db)
    await row_for(registry, albums, album_id)
    art = (await registry.artworks()).get(album_id)
    pinned = set(art.pinned_jobs) if art else set()
    _, rows = await _picture_rows(db, album_id)
    pictures = []
    for inner, row in sorted(rows.items()):
        kind = _kind_of(inner)
        if kind is None:
            continue
        slot = slot_key(*kind)
        version = (row.source_version or "")[:16]
        pictures.append(
            Picture(
                kind=kind[0],
                season=kind[1],
                slot=slot,
                url=f"/api/shows/{album_id}/artwork/file?"
                + urlencode({"path": inner, "v": version}),
                pinned=slot in pinned,
            )
        )
    state = state_of(request)
    return ArtworkOut(
        style_id=art.style_id if art else None,
        seed=art.seed if art else 0,
        use_cover=bool(art and art.use_cover),
        slot_seeds=dict(art.slot_seeds) if art else {},
        pictures=pictures,
        waiting=state.artwork_waiting.get(album_id, 0),
        syncing=state.running or state.wake.is_set(),
    )


@router.get("/shows/{album_id}/artwork/file")
async def artwork_file(
    album_id: UUID, path: str, user: CurrentUser, db: DbDep, settings: SettingsDep
) -> FileResponse:
    """A picture the app wrote for the show; nothing else is served."""
    target, rows = await _picture_rows(db, album_id)
    row = rows.get(path)
    folder = settings.jellyfin_dir if target == JELLYFIN else settings.kodi_output_dir
    if row is None or folder is None:
        raise ApiError(404, "picture_not_found")
    file = (folder / row.path).resolve()
    if not file.is_relative_to(folder.resolve()) or not file.is_file():
        raise ApiError(404, "picture_not_found")
    media_type = "image/png" if file.suffix == ".png" else "image/jpeg"
    return FileResponse(file, media_type=media_type, headers={"Cache-Control": "no-cache"})


# --- other pictures ---------------------------------------------------------------------


class Choice(BaseModel):
    style_id: str
    seed: int
    use_cover: bool
    slot_seeds: dict[str, int] = {}
    """Other frames for single pictures, by slot."""


class PreviewIn(BaseModel):
    change: Literal["style", "frames", "cover", "drawn"]
    slot: str | None = None
    """With `frames`: other frames for this picture only; all of them when left out."""
    style_id: str | None = None
    """With `style`: this style; another one at random when left out."""
    current: Choice | None = None
    """The choice shown last ("one more"); the saved one when left out."""
    seen_styles: list[str] = []
    """Styles already offered: another one is taken while there are others."""


class PreviewOut(BaseModel):
    choice: Choice
    pictures: dict[str, str]
    """Data URLs by slot, as the choice would draw them. Pinned pictures are not drawn: they
    stay as they are."""


async def draw_preview(jobs: list[ArtworkJob], source: HttpSource) -> list[bytes]:
    """Small pictures, drawn in the worker process. Raises ArtworkError."""
    return await shared_worker().run(preview_task, [job.to_dict() for job in jobs], source)


@router.post("/shows/{album_id}/artwork/preview")
async def preview(
    album_id: UUID,
    body: PreviewIn,
    user: CurrentUser,
    db: DbDep,
    albums: AlbumsDep,
    settings: SettingsDep,
    immich: ImmichFactoryDep,
    styles: StylesDep,
) -> PreviewOut:
    registry = Registry(db)
    row = await row_for(registry, albums, album_id)
    art = (await registry.artworks()).get(album_id)
    pinned = set(art.pinned_jobs) if art else set()
    current = body.current or Choice(
        style_id=art.style_id if art and art.style_id in styles else next(iter(sorted(styles))),
        seed=art.seed if art else 0,
        use_cover=bool(art and art.use_cover),
        slot_seeds=dict(art.slot_seeds) if art else {},
    )
    if current.style_id not in styles:
        raise ApiError(404, "style_not_found")
    slot = parse_slot(body.slot) if body.slot is not None else None
    if body.slot is not None and (slot is None or body.slot in pinned):
        raise ApiError(400, "artwork_slot")
    rng = random.Random()
    choice = current.model_copy(deep=True)
    if body.style_id is not None and body.style_id not in styles:
        raise ApiError(404, "style_not_found")
    if body.change == "style" and body.style_id is not None:
        choice.style_id = body.style_id
    elif body.change == "style":
        usable = sorted(set(styles) - await registry.disabled_styles()) or sorted(styles)
        fresh = [s for s in usable if s != current.style_id and s not in body.seen_styles]
        others = [s for s in usable if s != current.style_id]
        choice.style_id = rng.choice(fresh or others or usable)
    elif body.change == "frames" and body.slot is not None:
        choice.slot_seeds[body.slot] = rng.randrange(1, 1_000_000)
    elif body.change == "frames":
        choice.seed = rng.randrange(1, 1_000_000)
        # Other frames for all: the pictures given frames of their own follow too.
        choice.slot_seeds = {}
    else:
        choice.use_cover = body.change == "cover"

    show = await build(settings, immich, registry, albums[album_id], row)
    rows = await registry.frame_looks([e.asset_id for e in show.episodes])
    looks, _ = looks_of(show, rows)
    if not any(looks.values()):
        raise ApiError(409, "artwork_not_ready")
    jobs = plan_show(
        show,
        looks,
        styles[choice.style_id],
        choice.seed,
        seeds=choice.slot_seeds,
        season_posters=show.seasons != (SINGLE_SEASON,),
    )
    if slot is not None:
        keys = [slot]
    else:
        keys = [(kind, None) for kind in PREVIEW_KINDS]
        if choice.use_cover:
            keys.remove((OutputKind.SERIES_POSTER, None))
    wanted = [jobs[key] for key in keys if key in jobs and slot_key(*key) not in pinned]
    async with immich(settings.immich_api_key.get_secret_value()) as client:
        try:
            original = can_download(await client.api_key_info())
        except ImmichError as exc:
            raise ApiError(502, "immich_error") from exc
        source = client.http_source(original=original)
    try:
        drawn = await draw_preview(wanted, source) if wanted else []
    except ArtworkError as exc:
        raise ApiError(502, "artwork_failed") from exc
    pictures = {}
    for job, content in zip(wanted, drawn, strict=True):
        media = "image/png" if content.startswith(b"\x89PNG") else "image/jpeg"
        data = base64.b64encode(content).decode()
        pictures[slot_key(job.kind, job.season)] = f"data:{media};base64,{data}"
    return PreviewOut(choice=choice, pictures=pictures)


@router.put("/shows/{album_id}/artwork")
async def apply_choice(
    album_id: UUID,
    body: Choice,
    request: Request,
    user: CurrentUser,
    db: DbDep,
    albums: AlbumsDep,
    styles: StylesDep,
) -> dict[str, bool]:
    """Keep a choice: the next pass draws it. Pinned pictures stay as they are."""
    if body.style_id not in styles:
        raise ApiError(404, "style_not_found")
    if any(parse_slot(key) is None for key in body.slot_seeds):
        raise ApiError(400, "artwork_slot")
    registry = Registry(db)
    await row_for(registry, albums, album_id)
    await registry.save_artwork(
        album_id,
        body.style_id,
        seed=body.seed,
        use_cover=body.use_cover,
        slot_seeds=body.slot_seeds,
    )
    await registry.commit()
    state_of(request).request()
    return {"saved": True}


class PinsIn(BaseModel):
    slots: list[str] | None = None
    """The pictures to pin or unpin; all of them when left out."""
    pinned: bool


@router.put("/shows/{album_id}/artwork/pins")
async def pin(
    album_id: UUID,
    body: PinsIn,
    request: Request,
    user: CurrentUser,
    db: DbDep,
    albums: AlbumsDep,
    styles: StylesDep,
) -> dict[str, list[str]]:
    """Keep pictures exactly as they are drawn now, or let them follow the album again. Only a
    picture drawn already can be pinned. Answers with the pinned pictures."""
    registry = Registry(db)
    await row_for(registry, albums, album_id)
    art = (await registry.artworks()).get(album_id)
    drawn: dict[str, Any] = dict(art.drawn_jobs) if art else {}
    pinned: dict[str, Any] = dict(art.pinned_jobs) if art else {}
    slots = body.slots if body.slots is not None else list(drawn | pinned)
    for slot in slots:
        if body.pinned and slot in drawn and slot not in pinned:
            pinned[slot] = drawn[slot]
        elif not body.pinned:
            pinned.pop(slot, None)
    style_id = art.style_id if art else next(iter(sorted(styles)))
    await registry.save_artwork(album_id, style_id, pinned_jobs=pinned)
    await registry.commit()
    if not body.pinned:
        # An unpinned picture follows the album again: the next pass may draw it anew.
        state_of(request).request()
    return {"pinned": sorted(pinned)}
