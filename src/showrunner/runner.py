# SPDX-License-Identifier: AGPL-3.0-or-later
"""A sync with everything it needs, built from the settings: used by the commands and by the
scheduler of the server."""

import logging
from collections.abc import Collection
from pathlib import PurePosixPath
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from showrunner.config import Settings
from showrunner.immich.client import ImmichClient, excess_permissions, missing_permissions
from showrunner.model.show import Options
from showrunner.store.registry import Registry
from showrunner.sync.executor import Executor
from showrunner.sync.service import SyncReport, run_sync
from showrunner.targets.jellyfin.client import JellyfinClient, JellyfinError, tell_jellyfin
from showrunner.targets.jellyfin.layout import JellyfinLayout
from showrunner.targets.jellyfin.people import tend_people

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
            notify_media_server=jellyfin_client(settings) is not None,
        )
        if dry_run:
            await session.rollback()
    if dry_run:
        return report, notes

    jellyfin = jellyfin_client(settings)
    if jellyfin is None:
        if report.changed_folders or report.gone_albums:
            notes.append("Jellyfin is not configured: it will notice the changes on its own scan")
        return report, notes
    async with sessions() as session:
        registry = Registry(session)
        try:
            async with jellyfin:
                notes.extend(
                    await catch_up_jellyfin(
                        jellyfin,
                        registry,
                        jellyfin_output_path(settings),
                        report.visible_albums,
                    )
                )
                async with immich_client(settings) as immich:
                    notes.extend(
                        await tend_people(
                            jellyfin, immich, settings.person_prefix, await registry.people()
                        )
                    )
        except JellyfinError as exc:
            # The folder is right; only Jellyfin has not been told. The shows stay marked and
            # the next pass tries again.
            await session.rollback()
            report.errors.append(f"Jellyfin was not told about the changes, will retry: {exc}")
            log.error("Jellyfin was not told about the changes, will retry: %s", exc)
        report.media_server_pending = len(await registry.pending())
    return report, notes


async def catch_up_jellyfin(
    client: JellyfinClient,
    registry: Registry,
    output_folder: PurePosixPath,
    visible_albums: Collection[UUID],
) -> list[str]:
    """Tell Jellyfin about every show marked as pending, then clear the marks. A show whose album
    is still visible is refreshed; one whose album is gone needs a scan of the library. Raises
    JellyfinError, and keeps the marks, when Jellyfin does not answer."""
    pending = await registry.pending()
    if not pending:
        return []
    visible = set(visible_albums)
    done = await tell_jellyfin(client, output_folder, pending & visible, pending - visible)
    await registry.clear_pending(pending)
    await registry.commit()
    return done
