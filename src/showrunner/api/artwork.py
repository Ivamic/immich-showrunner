# SPDX-License-Identifier: AGPL-3.0-or-later
"""Artwork on the page: the styles that may be chosen, the pictures of a show, a look at other
pictures before they are made, and what the user keeps (frozen) or prefers (the cover).

A change is not drawn here for good: it is saved, and the full pass it asks for draws the
pictures and tells the media servers, as for every other edit."""

import base64
import random
from typing import Annotated, Literal
from urllib.parse import urlencode
from uuid import UUID

import anyio.to_thread
from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select

from showrunner.api.auth import CurrentUser, DbDep, ImmichFactoryDep, SettingsDep
from showrunner.api.errors import ApiError
from showrunner.api.shows import AlbumsDep, build, row_for, state_of
from showrunner.artwork.jobs import plan_show
from showrunner.artwork.make import ArtworkError, draw_small
from showrunner.artwork.style import OutputKind, Style
from showrunner.immich.client import ImmichError, can_download
from showrunner.model.show import SINGLE_SEASON
from showrunner.runner import styles as builtin_styles
from showrunner.store.models import ArtworkRow, FileRow
from showrunner.store.registry import Registry
from showrunner.sync.artwork import FROZEN_ALL, FROZEN_SHOW, NOT_FROZEN, looks_of
from showrunner.targets.base import JELLYFIN, KODI, FileKind

router = APIRouter()

Frozen = Literal["none", "show", "all"]
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
    pass, unless their pictures are frozen."""
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
    url: str


class ArtworkOut(BaseModel):
    style_id: str | None
    seed: int
    use_cover: bool
    frozen: Frozen
    pictures: list[Picture]


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
    album_id: UUID, user: CurrentUser, db: DbDep, albums: AlbumsDep
) -> ArtworkOut:
    registry = Registry(db)
    await row_for(registry, albums, album_id)
    art = (await registry.artworks()).get(album_id)
    _, rows = await _picture_rows(db, album_id)
    pictures = []
    for inner, row in sorted(rows.items()):
        kind = _kind_of(inner)
        if kind is None:
            continue
        version = (row.source_version or "")[:16]
        pictures.append(
            Picture(
                kind=kind[0],
                season=kind[1],
                url=f"/api/shows/{album_id}/artwork/file?"
                + urlencode({"path": inner, "v": version}),
            )
        )
    return ArtworkOut(
        style_id=art.style_id if art else None,
        seed=art.seed if art else 0,
        use_cover=bool(art and art.use_cover),
        frozen=_frozen(art),
        pictures=pictures,
    )


def _frozen(art: ArtworkRow | None) -> Frozen:
    if art is None or art.frozen not in (FROZEN_SHOW, FROZEN_ALL):
        return "none"
    return "show" if art.frozen == FROZEN_SHOW else "all"


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


class PreviewIn(BaseModel):
    change: Literal["style", "frames", "cover", "drawn"]
    current: Choice | None = None
    """The choice shown last ("one more"); the saved one when left out."""
    seen_styles: list[str] = []
    """Styles already offered: another one is taken while there are others."""


class PreviewOut(BaseModel):
    choice: Choice
    pictures: dict[str, str]
    """Data URLs of the poster, landscape picture and backdrop as the choice would draw them."""


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
    current = body.current or Choice(
        style_id=art.style_id if art and art.style_id in styles else next(iter(sorted(styles))),
        seed=art.seed if art else 0,
        use_cover=bool(art and art.use_cover),
    )
    rng = random.Random()
    choice = current.model_copy()
    if body.change == "style":
        usable = sorted(set(styles) - await registry.disabled_styles()) or sorted(styles)
        fresh = [s for s in usable if s != current.style_id and s not in body.seen_styles]
        others = [s for s in usable if s != current.style_id]
        choice.style_id = rng.choice(fresh or others or usable)
    elif body.change == "frames":
        choice.seed = rng.randrange(1, 1_000_000)
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
        season_posters=show.seasons != (SINGLE_SEASON,),
    )
    kinds = [k for k in PREVIEW_KINDS if not (choice.use_cover and k is OutputKind.SERIES_POSTER)]
    wanted = [jobs[(k, None)] for k in kinds if (k, None) in jobs]
    async with immich(settings.immich_api_key.get_secret_value()) as client:
        try:
            original = can_download(await client.api_key_info())
        except ImmichError as exc:
            raise ApiError(502, "immich_error") from exc

        def source(asset_id: UUID) -> tuple[str, dict[str, str]]:
            return client.video_source(asset_id, original=original)

        try:
            drawn = await anyio.to_thread.run_sync(draw_small, wanted, styles, source)
        except ArtworkError as exc:
            raise ApiError(502, "artwork_failed") from exc
    pictures = {}
    for job, content in zip(wanted, drawn, strict=True):
        media = "image/png" if content.startswith(b"\x89PNG") else "image/jpeg"
        pictures[job.kind.value] = f"data:{media};base64,{base64.b64encode(content).decode()}"
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
    """Keep a choice: the next pass draws it. Frozen pictures take the new ones as frozen."""
    if body.style_id not in styles:
        raise ApiError(404, "style_not_found")
    registry = Registry(db)
    await row_for(registry, albums, album_id)
    await registry.save_artwork(
        album_id, body.style_id, seed=body.seed, use_cover=body.use_cover, frozen_jobs=None
    )
    await registry.commit()
    state_of(request).request()
    return {"saved": True}


class FreezeIn(BaseModel):
    frozen: Frozen


@router.put("/shows/{album_id}/artwork/frozen")
async def freeze(
    album_id: UUID,
    body: FreezeIn,
    request: Request,
    user: CurrentUser,
    db: DbDep,
    albums: AlbumsDep,
    styles: StylesDep,
) -> dict[str, bool]:
    """Keep the pictures as they are (`show`: those of the show, `all`: of the seasons too), or
    let them follow the album again (`none`)."""
    registry = Registry(db)
    await row_for(registry, albums, album_id)
    art = (await registry.artworks()).get(album_id)
    style_id = art.style_id if art else next(iter(sorted(styles)))
    frozen = {"none": NOT_FROZEN, "show": FROZEN_SHOW, "all": FROZEN_ALL}[body.frozen]
    await registry.save_artwork(album_id, style_id, frozen=frozen, frozen_jobs=None)
    await registry.commit()
    state_of(request).request()
    return {"saved": True}
