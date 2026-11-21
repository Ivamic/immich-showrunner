# SPDX-License-Identifier: AGPL-3.0-or-later
"""A sync with everything it needs, built from the settings: used by the commands and by the
scheduler of the server."""

import logging
from collections.abc import Collection
from functools import cache
from pathlib import PurePosixPath
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from showrunner.artwork.style import Style, builtin_styles
from showrunner.config import Settings
from showrunner.immich.client import (
    ImmichClient,
    can_download,
    excess_permissions,
    missing_permissions,
)
from showrunner.model.show import Options
from showrunner.store.registry import Registry
from showrunner.sync.artwork import ArtworkContext
from showrunner.sync.executor import Executor
from showrunner.sync.service import Output, SyncReport, sync_outputs
from showrunner.sync.slideshow import SlideshowContext
from showrunner.sync.specials import SpecialsContext
from showrunner.targets.base import JELLYFIN, KODI
from showrunner.targets.jellyfin.client import JellyfinClient, JellyfinError, tell_jellyfin
from showrunner.targets.jellyfin.layout import JellyfinLayout
from showrunner.targets.jellyfin.people import tend_people
from showrunner.targets.kodi.client import KodiClient, KodiError, tell_kodi
from showrunner.targets.kodi.layout import KodiLayout
from showrunner.targets.specials import SlideshowStore

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


def kodi_client(settings: Settings) -> KodiClient | None:
    if not settings.kodi_url:
        return None
    return KodiClient(
        settings.kodi_url, settings.kodi_username, settings.kodi_password.get_secret_value()
    )


def jellyfin_output_path(settings: Settings) -> PurePosixPath:
    """The Jellyfin output folder as Jellyfin sees it."""
    folder = settings.jellyfin_dir
    return PurePosixPath(settings.jellyfin_output_path or (folder.as_posix() if folder else ""))


def outputs_from(settings: Settings, *, dry_run: bool) -> list[Output]:
    """The targets that have an output folder. Raises SetupError when none has."""
    roots = [m.target for m in settings.path_mappings]
    slideshows = settings.slideshow_media_path
    if slideshows is not None:
        roots.append(slideshows)  # the output folders link into the folder of slideshows
    outputs: list[Output] = []
    if settings.jellyfin_dir is not None:
        outputs.append(
            Output(
                JellyfinLayout(slideshows),
                None if dry_run else Executor(settings.jellyfin_dir, roots),
                notify=jellyfin_client(settings) is not None,
            )
        )
    if settings.kodi_output_dir is not None:
        outputs.append(
            Output(
                KodiLayout(settings.kodi_output_path, slideshows),
                None if dry_run else Executor(settings.kodi_output_dir, roots),
                notify=kodi_client(settings) is not None,
            )
        )
    if outputs and settings.slideshow_dir is not None:
        # The folder of slideshows holds files only (no links): no roots for links.
        outputs.insert(
            0, Output(SlideshowStore(), None if dry_run else Executor(settings.slideshow_dir, []))
        )
    if not outputs:
        raise SetupError(
            "no output folder: set SHOWRUNNER_JELLYFIN_OUTPUT_DIR or SHOWRUNNER_KODI_OUTPUT_DIR "
            "(in compose.yaml: SHOWRUNNER_JELLYFIN_OUTPUT_LOCATION or "
            "SHOWRUNNER_KODI_OUTPUT_LOCATION)"
        )
    return outputs


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


@cache
def styles() -> dict[str, Style]:
    """The styles shipped with the app, read once."""
    return builtin_styles()


async def artwork_context(
    settings: Settings, immich: ImmichClient
) -> tuple[ArtworkContext, str | None]:
    """What the artwork step needs for a pass, and a warning when the frames can not be read
    from the original videos."""
    original = can_download(await immich.api_key_info())
    warning = None
    if not original:
        warning = (
            "the Immich API key has no asset.download: frames for artwork are taken from the "
            "videos Immich converted for playing, which may be smaller"
        )
    context = ArtworkContext(
        styles=styles(),
        source=immich.http_source(original=original),
        budget_seconds=settings.artwork_budget_seconds,
    )
    return context, warning


async def sync_once(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    *,
    dry_run: bool = False,
    full: bool = True,
    force: bool = False,
) -> tuple[list[SyncReport], list[str]]:
    """Run one pass for every target and tell their media servers. Returns a report per target
    and notes for the log."""
    if not settings.path_mappings:
        raise SetupError("SHOWRUNNER_PATH_MAP is empty: the app would not know where to link")
    outputs = outputs_from(settings, dry_run=dry_run)
    notes: list[str] = []
    async with immich_client(settings) as immich, sessions() as session:
        notes.extend(await check_api_key(immich))
        artwork = None
        if settings.artwork and not dry_run:
            artwork, warning = await artwork_context(settings, immich)
            if warning:
                notes.append(warning)
        slideshow = None
        specials = None
        # Slideshows are switched on and off on the page (D-103); SHOWRUNNER_SLIDESHOW turns
        # them on whatever the page says, for development.
        setting = await Registry(session).slideshow_setting()
        enabled = settings.slideshow or (setting is not None and setting.enabled)
        credits = setting.credits if setting is not None else settings.slideshow_credits
        if enabled and not dry_run:
            full_size = can_download(await immich.api_key_info())
            if not full_size:
                notes.append(
                    "the Immich API key has no asset.download: photos for slideshows are taken "
                    "from the previews of Immich, which are smaller"
                )
            slideshow = SlideshowContext(
                full=full_size,
                data_dir=settings.data_dir,
                budget_seconds=settings.slideshow_budget_seconds,
            )
            if settings.data_dir is None:
                notes.append(
                    "SHOWRUNNER_DATA_DIR is not set: no slideshows are drawn, and photos get no "
                    "embeddings"
                )
            else:
                specials = SpecialsContext(
                    data_dir=settings.data_dir,
                    full=full_size,
                    styles=sorted(styles()),
                    credits=credits,
                    threads=settings.slideshow_threads,
                    budget_seconds=settings.slideshow_render_budget_seconds,
                )
        reports = await sync_outputs(
            immich=immich,
            registry=Registry(session),
            outputs=outputs,
            options=options_from(settings),
            full=full,
            force=force,
            artwork=artwork,
            slideshow=slideshow,
            specials=specials,
        )
        if dry_run:
            await session.rollback()
    if dry_run:
        return reports, notes
    for report in reports:
        if report.target == JELLYFIN:
            notes.extend(await tell_jellyfin_of(settings, sessions, report))
        elif report.target == KODI:
            notes.extend(await tell_kodi_of(settings, sessions, report))
    return reports, notes


async def tell_kodi_of(
    settings: Settings, sessions: async_sessionmaker[AsyncSession], report: SyncReport
) -> list[str]:
    """Tell Kodi about every show queued for it. A failure is noted in the report; the shows
    stay queued for the next pass (Kodi on a TV box is often off)."""
    kodi = kodi_client(settings)
    if kodi is None:
        if report.changed_folders or report.gone_albums:
            return ["Kodi is not configured: it shows the changes after an update of its library"]
        return []
    if not settings.kodi_output_path:
        report.errors.append("SHOWRUNNER_KODI_OUTPUT_PATH is not set: Kodi was not told")
        return []
    notes: list[str] = []
    async with sessions() as session:
        registry = Registry(session)
        try:
            async with kodi:
                notes.extend(await catch_up_kodi(kodi, registry, settings.kodi_output_path))
        except KodiError as exc:
            await session.rollback()
            report.errors.append(f"Kodi was not told about the changes, will retry: {exc}")
            log.warning("Kodi was not told about the changes, will retry: %s", exc)
        report.media_server_pending = len(await registry.pending(KODI))
    return notes


async def catch_up_kodi(client: KodiClient, registry: Registry, output_path: str) -> list[str]:
    """Tell Kodi about every show queued for it, then clear the queue. A show that has no files
    any more (its album is no longer shared, or it is hidden on the page) is removed from Kodi."""
    pending = await registry.pending(KODI)
    if not pending:
        return []
    with_files = {entry.album_id for entry in await registry.entries(KODI)}
    folders = {album: row.folder_name for album, row in (await registry.shows()).items()}
    changed = {album: folders[album] for album in pending & with_files if album in folders}
    done = await tell_kodi(client, output_path, changed, pending - with_files)
    await registry.clear_pending(pending, KODI)
    await registry.commit()
    return done


async def tell_jellyfin_of(
    settings: Settings, sessions: async_sessionmaker[AsyncSession], report: SyncReport
) -> list[str]:
    """Tell Jellyfin what the pass changed and take care of its people. A failure is noted in
    the report; the shows stay queued for the next pass."""
    jellyfin = jellyfin_client(settings)
    if jellyfin is None:
        if report.changed_folders or report.gone_albums:
            return ["Jellyfin is not configured: it will notice the changes on its own scan"]
        return []
    notes: list[str] = []
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
                            jellyfin,
                            immich,
                            settings.person_prefix,
                            await registry.people(),
                            await registry.descriptions(),
                        )
                    )
        except JellyfinError as exc:
            # The folder is right; only Jellyfin has not been told. The shows stay marked and
            # the next pass tries again.
            await session.rollback()
            report.errors.append(f"Jellyfin was not told about the changes, will retry: {exc}")
            log.error("Jellyfin was not told about the changes, will retry: %s", exc)
        report.media_server_pending = len(await registry.pending(JELLYFIN))
    return notes


async def catch_up_jellyfin(
    client: JellyfinClient,
    registry: Registry,
    output_folder: PurePosixPath,
    visible_albums: Collection[UUID],
) -> list[str]:
    """Tell Jellyfin about every show marked as pending, then clear the marks. A show whose album
    is still visible is refreshed; one whose album is gone needs a scan of the library. Raises
    JellyfinError, and keeps the marks, when Jellyfin does not answer."""
    pending = await registry.pending(JELLYFIN)
    if not pending:
        return []
    visible = set(visible_albums)
    folders = {album: row.folder_name for album, row in (await registry.shows()).items()}
    done = await tell_jellyfin(client, output_folder, pending & visible, pending - visible, folders)
    await registry.clear_pending(pending, JELLYFIN)
    await registry.commit()
    return done
