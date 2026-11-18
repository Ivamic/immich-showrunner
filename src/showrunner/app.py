# SPDX-License-Identifier: AGPL-3.0-or-later
"""The server: syncs on a schedule, serves the page and its API, answers `GET /api/health`."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any

import httpx2
from fastapi import FastAPI
from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

from showrunner import __version__
from showrunner.api import artwork, auth, people, shows, status
from showrunner.api.errors import ApiError, api_error_handler
from showrunner.config import Settings, get_settings
from showrunner.scheduler import State, scheduler
from showrunner.store.db import make_engine, make_session_factory, upgrade_async


class QuietAccessLog(logging.Filter):
    """Leaves out of the log the requests that only read and succeed: the files of the page, and
    the status it asks for every few seconds. Changes and every error stay."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 5:
            method, status = args[1], args[4]
            if method in ("GET", "HEAD") and isinstance(status, int) and status < 400:
                return False
        return True


def quiet_access_log() -> None:
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, QuietAccessLog) for f in access.filters):
        access.addFilter(QuietAccessLog())


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
    # uvicorn has set its logging up by now: it builds the app after that.
    quiet_access_log()
    state = State()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await upgrade_async(settings.database_url)
        engine = make_engine(settings.database_url)
        app.state.sessions = make_session_factory(engine)
        task = (
            asyncio.create_task(scheduler(settings, app.state.sessions, state))
            if run_scheduler
            else None
        )
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
    app.state.status = state
    app.add_exception_handler(ApiError, api_error_handler)
    app.include_router(auth.router, prefix="/api")
    app.include_router(status.router, prefix="/api")
    app.include_router(shows.router, prefix="/api")
    app.include_router(shows.thumbnails, prefix="/api")
    app.include_router(people.router, prefix="/api")
    app.include_router(artwork.router, prefix="/api")

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        """Always answers 200 while the server runs: a problem with Immich or a media server is
        in the body, so that a container health check does not restart the app because of them."""
        return {
            "version": __version__,
            "ok": state.last_ok,
            "held": state.held,
            "error": state.last_error,
            "shows": state.shows,
            "targets": state.targets,
            "jellyfin_pending": state.jellyfin_pending,
            "kodi_pending": state.kodi_pending,
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
