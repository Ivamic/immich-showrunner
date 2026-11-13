# SPDX-License-Identifier: AGPL-3.0-or-later
"""One pass of the sync: read Immich, plan, and carry the plan out.

If Immich can not be read completely, the pass stops before anything is planned: an album that
could not be read must never look like an album without videos."""

import logging
from dataclasses import dataclass, field, replace
from uuid import UUID

from showrunner.immich.client import ImmichClient
from showrunner.immich.models import Album
from showrunner.model.naming import show_folder_name
from showrunner.model.show import Options, SeasonMode, Skipped, build_show
from showrunner.store.registry import Registry
from showrunner.sync.executor import Executor, Outcome, Result, UnsafePathError
from showrunner.sync.plan import ActionType, Plan, make_plan
from showrunner.targets.base import DesiredFile, Target

log = logging.getLogger(__name__)


@dataclass
class SyncReport:
    dry_run: bool
    plan: Plan = field(default_factory=Plan)
    albums: int = 0
    # Albums read from Immich in this pass; the others had not changed.
    albums_read: int = 0
    # The pass would remove most of the links and was not carried out.
    held: bool = False
    created: int = 0
    replaced: int = 0
    removed: int = 0
    # Videos of the albums that did not become episodes, with the name of the album.
    skipped: list[tuple[str, Skipped]] = field(default_factory=list)
    # Paths where something the app did not create was found and left alone.
    foreign: list[Outcome] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    # Folders of the shows whose files changed, for telling the media server.
    changed_folders: dict[UUID, str] = field(default_factory=dict)
    # Albums that are no longer visible and whose files were removed.
    gone_albums: frozenset[UUID] = field(default_factory=frozenset)

    @property
    def ok(self) -> bool:
        return not self.held and not self.errors


async def run_sync(
    *,
    immich: ImmichClient,
    registry: Registry,
    executor: Executor | None,
    target: Target,
    options: Options,
    full: bool = True,
    force: bool = False,
) -> SyncReport:
    """Bring the output folder in line with the albums the Immich user can see.

    Without an `executor` this is a dry run: the plan is made and nothing is written, neither to
    the disk nor to the database. A quick pass (`full=False`) leaves alone the albums that have
    not changed since their files were last written. `force` carries out a mass removal."""
    report = SyncReport(dry_run=executor is None)
    albums = await immich.albums()
    shows = await registry.shows()
    report.albums = len(albums)

    desired: list[DesiredFile] = []
    untouched: set[UUID] = set()
    folders: dict[UUID, str] = {}
    read: list[Album] = []
    for album in albums:
        row = shows.get(album.id)
        if (
            row is not None
            and not full
            and _unchanged(album, row.album_updated_at, row.assets_modified_at)
        ):
            untouched.add(album.id)
            folders[album.id] = row.folder_name
            continue
        if row is None and executor is not None:
            row = await registry.add_show(album.id, album.album_name)
        folder = (
            row.folder_name if row is not None else show_folder_name(album.album_name, album.id)
        )
        mode = SeasonMode(row.season_mode) if row is not None else options.season_mode
        videos = [video async for video in immich.album_videos(album.id)]
        show = build_show(album, videos, replace(options, season_mode=mode))
        report.skipped.extend((album.album_name, item) for item in show.skipped)
        desired.extend(target.files(show, folder))
        folders[album.id] = folder
        read.append(album)
    report.albums_read = len(read)

    plan = make_plan(desired, await registry.entries(), untouched_albums=untouched)
    report.plan = plan
    report.changed_folders = {
        album_id: folders[album_id] for album_id in plan.changed_albums if album_id in folders
    }
    report.gone_albums = frozenset(plan.changed_albums - folders.keys())
    if plan.is_mass_removal and not force:
        report.held = True
        log.error(
            "the sync would remove %d of %d links and was not carried out",
            plan.links_removed,
            plan.links_before,
        )
        return report
    if executor is None:
        return report

    failed: set[UUID] = set()
    for action in plan.actions:
        try:
            outcome = executor.apply(action)
        except (UnsafePathError, OSError) as exc:
            failed.add(action.album_id)
            report.errors.append(f"{action.type.value} {action.path}: {exc}")
            log.error("%s %s failed: %s", action.type.value, action.path, exc)
            continue
        if outcome.result is Result.FOREIGN:
            report.foreign.append(outcome)
            log.warning("%s: %s; left alone", action.path, outcome.detail)
        if outcome.forget:
            await registry.forget(action.path)
        elif outcome.record and action.desired is not None:
            await registry.record(action.desired)
        if outcome.result is Result.DONE:
            if action.type is ActionType.CREATE:
                report.created += 1
            elif action.type is ActionType.REPLACE:
                report.replaced += 1
            else:
                report.removed += 1

    for album in read:
        if album.id not in failed:
            await registry.set_stamps(
                album.id, album.updated_at, album.last_modified_asset_timestamp
            )
    await registry.commit()
    return report


def _unchanged(album: Album, updated_at: object, assets_modified_at: object) -> bool:
    return (
        updated_at is not None
        and album.updated_at == updated_at
        and album.last_modified_asset_timestamp == assets_modified_at
    )
