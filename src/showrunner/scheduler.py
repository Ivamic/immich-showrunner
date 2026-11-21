# SPDX-License-Identifier: AGPL-3.0-or-later
"""The sync on a schedule, the state of the last pass, and a pass on request from the page."""

import asyncio
import contextlib
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from showrunner.config import Settings
from showrunner.immich.client import ImmichError
from showrunner.runner import SetupError, sync_once
from showrunner.sync.service import SyncReport
from showrunner.targets.base import JELLYFIN, KODI

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
    # The targets of the last pass, and the shows their media servers still have to be told about.
    targets: list[str] = field(default_factory=list)
    jellyfin_pending: int = 0
    kodi_pending: int = 0
    created: int = 0
    replaced: int = 0
    removed: int = 0
    notes: list[str] = field(default_factory=list)
    skipped: list[Skip] = field(default_factory=list)
    pictures_failed: list[str] = field(default_factory=list)
    # Videos still to look at for the pictures, per album, as the last pass left them.
    artwork_waiting: dict[UUID, int] = field(default_factory=dict)
    # Slideshows drawn by the last pass and left for the next ones.
    slideshows_drawn: int = 0
    slideshows_waiting: int = 0
    foreign: list[Foreign] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    # A pass asked for from the page; `force` carries out a held mass removal.
    wake: asyncio.Event = field(default_factory=asyncio.Event)
    force_next: bool = False
    full_next: bool = False

    def record(self, reports: list[SyncReport], notes: list[str]) -> None:
        """Keep what a pass did, summed over its targets."""
        held = [r for r in reports if r.held]
        self.last_ok = all(r.ok for r in reports)
        self.held = bool(held)
        self.held_links_removed = sum(r.plan.links_removed for r in held)
        self.held_links_before = sum(r.plan.links_before for r in held)
        self.errors = [e for r in reports for e in r.errors]
        self.last_error = "; ".join(self.errors) or (
            "held: the sync would remove most of the links" if held else ""
        )
        first = reports[0]
        self.shows = first.albums
        self.targets = [r.target for r in reports]
        self.jellyfin_pending = sum(r.media_server_pending for r in reports if r.target == JELLYFIN)
        self.kodi_pending = sum(r.media_server_pending for r in reports if r.target == KODI)
        self.created = sum(r.created for r in reports)
        self.replaced = sum(r.replaced for r in reports)
        self.removed = sum(r.removed for r in reports)
        self.notes = notes
        self.skipped = [Skip(album, s.file_name, s.reason.value) for album, s in first.skipped][
            :MAX_LISTED
        ]
        self.pictures_failed = [p for r in reports for p in r.pictures_failed][:MAX_LISTED]
        self.artwork_waiting = dict(first.artwork_waiting)
        # A slideshow drawn once counts once, though every output folder gets it.
        self.slideshows_drawn = max((r.slideshows_drawn for r in reports), default=0)
        self.slideshows_waiting = max((r.slideshows_waiting for r in reports), default=0)
        self.foreign = [Foreign(str(o.action.path), o.detail) for r in reports for o in r.foreign][
            :MAX_LISTED
        ]

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
        reports, notes = await sync_once(settings, sessions, full=full, force=force)
    except (ImmichError, SetupError, OSError) as exc:
        state.failed(str(exc))
        log.error("sync failed: %s", exc)
    except Exception as exc:  # the scheduler must outlive a bug in one pass
        state.failed(repr(exc))
        log.exception("sync failed")
    else:
        state.record(reports, notes)
        if full and not state.held:
            state.last_full_sync_at = now
        for report in reports:
            if not report.plan.is_empty:
                log.info(
                    "sync %s: %d created, %d replaced, %d removed",
                    report.target,
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
