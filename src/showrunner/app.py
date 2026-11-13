# SPDX-License-Identifier: AGPL-3.0-or-later
"""The server: syncs on a schedule and answers `GET /api/health`."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx2
from fastapi import FastAPI
from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

from showrunner import __version__
from showrunner.api import auth
from showrunner.api.errors import ApiError, api_error_handler
from showrunner.config import Settings, get_settings
from showrunner.immich.client import ImmichError
from showrunner.runner import SetupError, sync_once
from showrunner.store.db import make_engine, make_session_factory, upgrade_async

log = logging.getLogger(__name__)

# Things that a quick pass can not see (a person renamed in Immich, a setting changed) are picked
# up by a full pass.
FULL_SYNC_EVERY_SECONDS = 3600


@dataclass
class State:
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_sync_at: datetime | None = None
    last_full_sync_at: datetime | None = None
    last_ok: bool | None = None
    last_error: str = ""
    held: bool = False
    shows: int = 0
    # Shows whose changes Jellyfin has not yet confirmed.
    jellyfin_pending: int = 0
    notes: list[str] = field(default_factory=list)


async def scheduler(settings: Settings, state: State, app: FastAPI) -> None:
    sessions = app.state.sessions
    while True:
        now = datetime.now(UTC)
        full = (
            state.last_full_sync_at is None
            or (now - state.last_full_sync_at).total_seconds() >= FULL_SYNC_EVERY_SECONDS
        )
        try:
            report, notes = await sync_once(settings, sessions, full=full)
        except (ImmichError, SetupError, OSError) as exc:
            state.last_ok, state.last_error = False, str(exc)
            log.error("sync failed: %s", exc)
        except Exception as exc:  # the scheduler must outlive a bug in one pass
            state.last_ok, state.last_error = False, repr(exc)
            log.exception("sync failed")
        else:
            state.last_ok = report.ok
            state.held = report.held
            state.last_error = "; ".join(report.errors) or (
                "held: the sync would remove most of the links; run `showrunner sync --force` "
                "if that is right"
                if report.held
                else ""
            )
            state.shows = report.albums
            state.jellyfin_pending = report.media_server_pending
            state.notes = notes
            if full and not report.held:
                state.last_full_sync_at = now
            if not report.plan.is_empty:
                log.info(
                    "sync: %d created, %d replaced, %d removed",
                    report.created,
                    report.replaced,
                    report.removed,
                )
            for note in notes:
                log.info("%s", note)
        state.last_sync_at = datetime.now(UTC)
        await asyncio.sleep(settings.sync_interval_seconds)


class SPAStaticFiles(StaticFiles):
    """Serves the built web page; unknown paths fall back to index.html (routing in the page)."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            # Unknown API paths stay real 404s. `path` has backslashes on Windows.
            first_segment = path.replace("\\", "/").split("/", 1)[0]
            if exc.status_code != 404 or first_segment == "api":
                raise
            return await super().get_response("index.html", scope)


def create_app(
    settings: Settings | None = None,
    *,
    run_scheduler: bool = True,
    immich_transport: httpx2.AsyncBaseTransport | None = None,
) -> FastAPI:
    """The server. Tests pass their own settings, no scheduler and a fake Immich."""
    settings = settings or get_settings()
    state = State()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await upgrade_async(settings.database_url)
        engine = make_engine(settings.database_url)
        app.state.sessions = make_session_factory(engine)
        task = asyncio.create_task(scheduler(settings, state, app)) if run_scheduler else None
        try:
            yield
        finally:
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            await engine.dispose()

    app = FastAPI(title="Showrunner for Immich", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.immich_transport = immich_transport
    app.add_exception_handler(ApiError, api_error_handler)
    app.include_router(auth.router, prefix="/api")

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        """Always answers 200 while the server runs: a problem with Immich or Jellyfin is in the
        body, so that a container health check does not restart the app because of them."""
        return {
            "version": __version__,
            "ok": state.last_ok,
            "held": state.held,
            "error": state.last_error,
            "shows": state.shows,
            "jellyfin_pending": state.jellyfin_pending,
            "last_sync_at": state.last_sync_at.isoformat() if state.last_sync_at else None,
            "last_full_sync_at": (
                state.last_full_sync_at.isoformat() if state.last_full_sync_at else None
            ),
            "notes": state.notes,
        }

    static_dir = settings.static_dir
    if static_dir is not None and Path(static_dir, "index.html").is_file():
        app.mount("/", SPAStaticFiles(directory=static_dir, html=True), name="page")
    return app
