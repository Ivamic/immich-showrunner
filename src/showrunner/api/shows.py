# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shows and episodes on the page: what the app makes of the shared albums, and the edits of the
user on top. Every edit asks for a full pass, so that it reaches Jellyfin within seconds."""

from dataclasses import replace
from datetime import datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from showrunner.api.auth import CurrentUser, DbDep, ImmichFactoryDep, SettingsDep
from showrunner.api.errors import ApiError
from showrunner.config import Settings
from showrunner.immich.client import ImmichError, ImmichUnreachableError
from showrunner.immich.models import Album
from showrunner.model.show import EpisodeEdit, SeasonMode, Show, build_show
from showrunner.runner import options_from
from showrunner.scheduler import State
from showrunner.store.models import FileRow, ShowRow
from showrunner.store.registry import Registry
from showrunner.targets.base import FileKind

router = APIRouter(prefix="/shows")

# Moving an episode after the last one of its season puts it this much later.
MOVE_STEP = timedelta(minutes=1)


class ShowOut(BaseModel):
    album_id: UUID
    album_name: str
    title: str
    title_edited: bool
    hidden: bool
    season_mode: SeasonMode
    episodes: int
    cover_asset_id: UUID | None


class EpisodeOut(BaseModel):
    asset_id: UUID
    file_name: str
    filmed_at: datetime
    season: int
    number: int
    title: str
    auto_title: str
    title_edited: bool
    plot: str
    auto_plot: str
    plot_edited: bool
    moved: bool
    hidden: bool


class ShowDetail(ShowOut):
    episode_list: list[EpisodeOut]


class ShowPatch(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    hidden: bool | None = None
    season_mode: SeasonMode | None = None


class EpisodePatch(BaseModel):
    """A field that is sent changes; `null` gives it back to Immich."""

    title: str | None = Field(default=None, max_length=300)
    plot: str | None = Field(default=None, max_length=10000)
    hidden: bool | None = None
    sort_at: Literal[None] = None  # only `null`: back to the order of filming


class Move(BaseModel):
    """Put the episode between two episodes of its season; one of them may be missing."""

    after: UUID | None = None
    before: UUID | None = None


def state_of(request: Request) -> State:
    state: State = request.app.state.status
    return state


async def visible_albums(immich: ImmichFactoryDep, settings: SettingsDep) -> dict[UUID, Album]:
    try:
        async with immich(settings.immich_api_key.get_secret_value()) as client:
            return {album.id: album for album in await client.albums()}
    except ImmichUnreachableError as exc:
        raise ApiError(502, "immich_unreachable") from exc
    except ImmichError as exc:
        raise ApiError(502, "immich_error") from exc


AlbumsDep = Annotated[dict[UUID, Album], Depends(visible_albums)]


async def episode_counts(db: DbDep) -> dict[UUID, int]:
    rows = await db.execute(
        select(FileRow.album_id, func.count())
        .where(FileRow.kind == FileKind.LINK.value)
        .group_by(FileRow.album_id)
    )
    return {album_id: count for album_id, count in rows}


def show_out(album: Album, row: ShowRow | None, episodes: int) -> ShowOut:
    title = (row.title if row is not None else None) or album.album_name
    return ShowOut(
        album_id=album.id,
        album_name=album.album_name,
        title=title,
        title_edited=bool(row is not None and row.title),
        hidden=bool(row is not None and row.hidden),
        season_mode=SeasonMode(row.season_mode) if row is not None else SeasonMode.YEAR,
        episodes=episodes,
        cover_asset_id=album.album_thumbnail_asset_id,
    )


async def row_for(registry: Registry, albums: dict[UUID, Album], album_id: UUID) -> ShowRow:
    """The show of a visible album, recorded now if the app has not synced it yet."""
    album = albums.get(album_id)
    if album is None:
        raise ApiError(404, "show_not_found")
    row = (await registry.shows()).get(album_id)
    return row if row is not None else await registry.add_show(album.id, album.album_name)


async def build(
    settings: Settings, immich: ImmichFactoryDep, registry: Registry, album: Album, row: ShowRow
) -> Show:
    options = replace(options_from(settings), season_mode=SeasonMode(row.season_mode))
    async with immich(settings.immich_api_key.get_secret_value()) as client:
        videos = [video async for video in client.album_videos(album.id)]
    return build_show(
        album, videos, options, await registry.episode_edits(album.id), Registry.show_edit(row)
    )


def detail(album: Album, row: ShowRow, show: Show) -> ShowDetail:
    episodes = sorted(
        [*show.episodes, *show.hidden], key=lambda e: (e.season, e.number == 0, e.number)
    )
    return ShowDetail(
        **show_out(album, row, len(show.episodes)).model_dump(),
        episode_list=[
            EpisodeOut(
                asset_id=e.asset_id,
                file_name=e.original_file_name,
                filmed_at=e.filmed_at,
                season=e.season,
                number=e.number,
                title=e.title,
                auto_title=e.auto_title,
                title_edited=e.title != e.auto_title,
                plot=e.plot,
                auto_plot=e.auto_plot,
                plot_edited=e.plot != e.auto_plot,
                moved=e.sort_at is not None,
                hidden=e.number == 0,
            )
            for e in episodes
        ],
    )


@router.get("")
async def list_shows(user: CurrentUser, db: DbDep, albums: AlbumsDep) -> list[ShowOut]:
    rows = await Registry(db).shows()
    counts = await episode_counts(db)
    shows = [show_out(a, rows.get(a.id), counts.get(a.id, 0)) for a in albums.values()]
    return sorted(shows, key=lambda s: s.title.casefold())


@router.get("/{album_id}")
async def get_show(
    album_id: UUID,
    user: CurrentUser,
    db: DbDep,
    albums: AlbumsDep,
    settings: SettingsDep,
    immich: ImmichFactoryDep,
) -> ShowDetail:
    registry = Registry(db)
    row = await row_for(registry, albums, album_id)
    await registry.commit()
    show = await build(settings, immich, registry, albums[album_id], row)
    return detail(albums[album_id], row, show)


@router.patch("/{album_id}")
async def edit_show(
    album_id: UUID,
    body: ShowPatch,
    request: Request,
    user: CurrentUser,
    db: DbDep,
    albums: AlbumsDep,
) -> ShowOut:
    registry = Registry(db)
    row = await row_for(registry, albums, album_id)
    if "title" in body.model_fields_set:
        row.title = (body.title or "").strip() or None
    if body.hidden is not None:
        row.hidden = body.hidden
    if body.season_mode is not None:
        row.season_mode = body.season_mode.value
    await registry.commit()
    state_of(request).request()
    return show_out(albums[album_id], row, (await episode_counts(db)).get(album_id, 0))


@router.patch("/{album_id}/episodes/{asset_id}")
async def edit_episode(
    album_id: UUID,
    asset_id: UUID,
    body: EpisodePatch,
    request: Request,
    user: CurrentUser,
    db: DbDep,
    albums: AlbumsDep,
) -> dict[str, bool]:
    registry = Registry(db)
    await row_for(registry, albums, album_id)
    edit = (await registry.episode_edits(album_id)).get(asset_id, EpisodeEdit())
    sent = body.model_fields_set
    edit = EpisodeEdit(
        title=((body.title or "").strip() or None) if "title" in sent else edit.title,
        plot=body.plot if "plot" in sent else edit.plot,
        sort_at=None if "sort_at" in sent else edit.sort_at,
        hidden=body.hidden if body.hidden is not None else edit.hidden,
    )
    await registry.save_episode_edit(album_id, asset_id, edit)
    await registry.commit()
    state_of(request).request()
    return {"saved": True}


@router.post("/{album_id}/episodes/{asset_id}/move")
async def move_episode(
    album_id: UUID,
    asset_id: UUID,
    body: Move,
    request: Request,
    user: CurrentUser,
    db: DbDep,
    albums: AlbumsDep,
    settings: SettingsDep,
    immich: ImmichFactoryDep,
) -> dict[str, bool]:
    registry = Registry(db)
    row = await row_for(registry, albums, album_id)
    show = await build(settings, immich, registry, albums[album_id], row)
    by_id = {e.asset_id: e for e in show.episodes}
    episode = by_id.get(asset_id)
    if episode is None or (body.after is None and body.before is None):
        raise ApiError(400, "move_invalid")
    neighbours = [by_id.get(n) for n in (body.after, body.before) if n is not None]
    if any(n is None or n.season != episode.season for n in neighbours):
        raise ApiError(400, "move_other_season")

    def key(e_id: UUID) -> datetime:
        e = by_id[e_id]
        return e.sort_at or e.filmed_at

    if body.after is not None and body.before is not None:
        a, b = key(body.after), key(body.before)
        sort_at = a + (b - a) / 2
    elif body.after is not None:
        sort_at = key(body.after) + MOVE_STEP
    else:
        assert body.before is not None
        sort_at = key(body.before) - MOVE_STEP
    edit = (await registry.episode_edits(album_id)).get(asset_id, EpisodeEdit())
    await registry.save_episode_edit(
        album_id,
        asset_id,
        EpisodeEdit(title=edit.title, plot=edit.plot, sort_at=sort_at, hidden=edit.hidden),
    )
    await registry.commit()
    state_of(request).request()
    return {"saved": True}


thumbnails = APIRouter()


@thumbnails.get("/thumbnails/{asset_id}")
async def thumbnail(
    asset_id: UUID,
    user: CurrentUser,
    settings: SettingsDep,
    immich: ImmichFactoryDep,
    size: Literal["thumbnail", "preview"] = "thumbnail",
) -> Response:
    """A picture for the page, read with the key of the app: only assets it may see."""
    try:
        async with immich(settings.immich_api_key.get_secret_value()) as client:
            content, media_type = await client.thumbnail(asset_id, size)
    except ImmichUnreachableError as exc:
        raise ApiError(502, "immich_unreachable") from exc
    except ImmichError as exc:
        raise ApiError(404, "picture_not_found") from exc
    return Response(
        content=content,
        media_type=media_type,
        headers={"Cache-Control": "private, max-age=3600"},
    )
