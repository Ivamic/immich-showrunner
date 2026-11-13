# SPDX-License-Identifier: AGPL-3.0-or-later
"""The sync on a schedule, the state of the last pass, and a pass on request from the page."""

import asyncio
import contextlib
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from showrunner.config import Settings
from showrunner.immich.client import ImmichError
from showrunner.runner import SetupError, sync_once
from showrunner.sync.service import SyncReport

log = logging.getLogger(__name__)

# Things that a quick pass can not see (a person renamed in Immich, a setting changed) are picked
# up by a full pass.
FULL_SYNC_EVERY_SECONDS = 3600
MAX_LISTED = 200


@dataclass
class Skip:
    album: str
    file: str
    reason: str


@dataclass
class Foreign:
    path: str
    detail: str


@dataclass
class State:
    """What the page and /api/health show. Kept in memory: after a restart it fills again with
    the first pass."""

    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    running: bool = False
    last_sync_at: datetime | None = None
    last_full_sync_at: datetime | None = None
    last_ok: bool | None = None
    last_error: str = ""
    held: bool = False
    held_links_removed: int = 0
    held_links_before: int = 0
    shows: int = 0
    jellyfin_pending: int = 0
    created: int = 0
    replaced: int = 0
    removed: int = 0
    notes: list[str] = field(default_factory=list)
    skipped: list[Skip] = field(default_factory=list)
    pictures_failed: list[str] = field(default_factory=list)
    foreign: list[Foreign] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    # A pass asked for from the page; `force` carries out a held mass removal.
    wake: asyncio.Event = field(default_factory=asyncio.Event)
    force_next: bool = False
    full_next: bool = False

    def record(self, report: SyncReport, notes: list[str]) -> None:
        self.last_ok = report.ok
        self.held = report.held
        self.held_links_removed = report.plan.links_removed if report.held else 0
        self.held_links_before = report.plan.links_before if report.held else 0
        self.errors = list(report.errors)
        self.last_error = "; ".join(report.errors) or (
            "held: the sync would remove most of the links" if report.held else ""
        )
        self.shows = report.albums
        self.jellyfin_pending = report.media_server_pending
        self.created, self.replaced, self.removed = report.created, report.replaced, report.removed
        self.notes = notes
        self.skipped = [Skip(album, s.file_name, s.reason.value) for album, s in report.skipped][
            :MAX_LISTED
        ]
        self.pictures_failed = report.pictures_failed[:MAX_LISTED]
        self.foreign = [Foreign(str(o.action.path), o.detail) for o in report.foreign][:MAX_LISTED]

    def failed(self, message: str) -> None:
        self.last_ok, self.last_error, self.errors = False, message, [message]

    def request(self, *, force: bool = False) -> None:
        """A full pass as soon as possible."""
        self.full_next = True
        self.force_next = self.force_next or force
        self.wake.set()


async def one_pass(
    settings: Settings, sessions: async_sessionmaker[AsyncSession], state: State
) -> None:
    now = datetime.now(UTC)
    full = (
        state.full_next
        or state.last_full_sync_at is None
        or (now - state.last_full_sync_at).total_seconds() >= FULL_SYNC_EVERY_SECONDS
    )
    force, state.force_next, state.full_next = state.force_next, False, False
    state.running = True
    try:
        report, notes = await sync_once(settings, sessions, full=full, force=force)
    except (ImmichError, SetupError, OSError) as exc:
        state.failed(str(exc))
        log.error("sync failed: %s", exc)
    except Exception as exc:  # the scheduler must outlive a bug in one pass
        state.failed(repr(exc))
        log.exception("sync failed")
    else:
        state.record(report, notes)
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
    finally:
        state.running = False
        state.last_sync_at = datetime.now(UTC)


async def scheduler(
    settings: Settings, sessions: async_sessionmaker[AsyncSession], state: State
) -> None:
    while True:
        # A request that comes while a pass runs is kept: the wait below then ends at once.
        state.wake.clear()
        await one_pass(settings, sessions, state)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(state.wake.wait(), timeout=settings.sync_interval_seconds)
