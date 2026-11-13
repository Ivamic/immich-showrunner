# SPDX-License-Identifier: AGPL-3.0-or-later
"""A sync with everything it needs, built from the settings: used by the commands and by the
scheduler of the server."""

import logging
from pathlib import PurePosixPath

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from showrunner.config import Settings
from showrunner.immich.client import ImmichClient, excess_permissions, missing_permissions
from showrunner.model.show import Options
from showrunner.store.registry import Registry
from showrunner.sync.executor import Executor
from showrunner.sync.service import SyncReport, run_sync
from showrunner.targets.jellyfin.client import JellyfinClient, JellyfinError, tell_jellyfin
from showrunner.targets.jellyfin.layout import JellyfinLayout

log = logging.getLogger(__name__)


class SetupError(Exception):
    """The settings do not allow a sync: said in words for the person who set the app up."""


def options_from(settings: Settings) -> Options:
    return Options(
        path_mappings=settings.path_mappings,
        show_prefix=settings.show_prefix,
        person_prefix=settings.person_prefix,
        title_max_length=settings.title_max_length,
        date_title_format=settings.title_date_format,
    )


def immich_client(settings: Settings) -> ImmichClient:
    return ImmichClient(settings.immich_url, settings.immich_api_key.get_secret_value())


def jellyfin_client(settings: Settings) -> JellyfinClient | None:
    key = settings.jellyfin_api_key.get_secret_value()
    if not settings.jellyfin_url or not key:
        return None
    return JellyfinClient(settings.jellyfin_url, key)


def jellyfin_output_path(settings: Settings) -> PurePosixPath:
    return PurePosixPath(settings.jellyfin_output_path or settings.output_dir.as_posix())


async def check_api_key(immich: ImmichClient) -> list[str]:
    """Stop when the key can not read what the app needs; return warnings about what it could do
    beyond reading."""
    info = await immich.api_key_info()
    missing = missing_permissions(info)
    if missing:
        raise SetupError("the Immich API key lacks the permissions: " + ", ".join(sorted(missing)))
    excess = excess_permissions(info)
    if excess:
        return [
            "the Immich API key can do more than the app needs ("
            + ", ".join(sorted(excess))
            + "); a key with only album.read, asset.read, asset.view, person.read and user.read "
            "is safer"
        ]
    return []


async def sync_once(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    *,
    dry_run: bool = False,
    full: bool = True,
    force: bool = False,
) -> tuple[SyncReport, list[str]]:
    """Run one pass and tell Jellyfin. Returns the report and notes for the log."""
    if not settings.path_mappings:
        raise SetupError("SHOWRUNNER_PATH_MAP is empty: the app would not know where to link")
    notes: list[str] = []
    executor = None
    if not dry_run:
        executor = Executor(settings.output_dir, [m.target for m in settings.path_mappings])
    async with immich_client(settings) as immich, sessions() as session:
        notes.extend(await check_api_key(immich))
        report = await run_sync(
            immich=immich,
            registry=Registry(session),
            executor=executor,
            target=JellyfinLayout(),
            options=options_from(settings),
            full=full,
            force=force,
        )
        if dry_run:
            await session.rollback()
    if dry_run or report.held:
        return report, notes

    jellyfin = jellyfin_client(settings)
    changed = set(report.changed_folders)
    if jellyfin is None:
        if changed or report.gone_albums:
            notes.append("Jellyfin is not configured: it will notice the changes on its own scan")
        return report, notes
    try:
        async with jellyfin:
            notes.extend(
                await tell_jellyfin(
                    jellyfin, jellyfin_output_path(settings), changed, set(report.gone_albums)
                )
            )
    except JellyfinError as exc:
        # The folder is right; only Jellyfin has not been told. The next full pass does not
        # repeat it, so say it loudly.
        report.errors.append(f"Jellyfin was not told about the changes: {exc}")
        log.error("Jellyfin was not told about the changes: %s", exc)
    return report, notes
