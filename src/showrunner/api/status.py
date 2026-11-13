# SPDX-License-Identifier: AGPL-3.0-or-later
"""The state of the sync for the page, and a pass on request."""

from datetime import datetime

from fastapi import APIRouter, Request
from pydantic import BaseModel

from showrunner import __version__
from showrunner.api.auth import CurrentUser
from showrunner.scheduler import State

router = APIRouter()


class SkipOut(BaseModel):
    album: str
    file: str
    reason: str


class ForeignOut(BaseModel):
    path: str
    detail: str


class Status(BaseModel):
    version: str
    running: bool
    ok: bool | None
    error: str
    errors: list[str]
    held: bool
    held_links_removed: int
    held_links_before: int
    shows: int
    jellyfin_pending: int
    created: int
    replaced: int
    removed: int
    last_sync_at: datetime | None
    last_full_sync_at: datetime | None
    sync_interval_seconds: int
    skipped: list[SkipOut]
    pictures_failed: list[str]
    foreign: list[ForeignOut]


class SyncRequest(BaseModel):
    # Carry out a mass removal that the last pass held.
    force: bool = False


def state_of(request: Request) -> State:
    state: State = request.app.state.status
    return state


@router.get("/status")
async def status(request: Request, user: CurrentUser) -> Status:
    s = state_of(request)
    return Status(
        version=__version__,
        running=s.running,
        ok=s.last_ok,
        error=s.last_error,
        errors=s.errors,
        held=s.held,
        held_links_removed=s.held_links_removed,
        held_links_before=s.held_links_before,
        shows=s.shows,
        jellyfin_pending=s.jellyfin_pending,
        created=s.created,
        replaced=s.replaced,
        removed=s.removed,
        last_sync_at=s.last_sync_at,
        last_full_sync_at=s.last_full_sync_at,
        sync_interval_seconds=request.app.state.settings.sync_interval_seconds,
        skipped=[SkipOut(album=x.album, file=x.file, reason=x.reason) for x in s.skipped],
        pictures_failed=s.pictures_failed,
        foreign=[ForeignOut(path=x.path, detail=x.detail) for x in s.foreign],
    )


@router.post("/sync", status_code=202)
async def sync_now(body: SyncRequest, request: Request, user: CurrentUser) -> dict[str, bool]:
    """A full pass right away (after the one that runs, if any)."""
    state_of(request).request(force=body.force)
    return {"queued": True}
