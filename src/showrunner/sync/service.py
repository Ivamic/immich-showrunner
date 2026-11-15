# SPDX-License-Identifier: AGPL-3.0-or-later
"""One pass of the sync: read Immich once, then plan and carry the plan out for every target.

If Immich can not be read completely, the pass stops before anything is planned: an album that
could not be read must never look like an album without videos."""

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from uuid import UUID

from showrunner.immich.client import (
    ImmichAuthError,
    ImmichClient,
    ImmichError,
    ImmichUnreachableError,
)
from showrunner.immich.models import Album
from showrunner.model.naming import show_folder_name
from showrunner.model.show import Options, SeasonMode, Show, Skipped, build_show
from showrunner.store.registry import Registry
from showrunner.sync.executor import Executor, Outcome, Result, UnsafePathError
from showrunner.sync.plan import Action, ActionType, Plan, make_plan
from showrunner.targets.base import DesiredFile, ImageSource, Target

log = logging.getLogger(__name__)


@dataclass
class SyncReport:
    """What a pass did for one target. The counts of albums, the skipped videos and the people
    come from Immich and are the same for every target."""

    dry_run: bool
    target: str = ""
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
    # Albums the Immich user can see in this pass.
    visible_albums: frozenset[UUID] = field(default_factory=frozenset)
    # Shows the media server still has to be told about, after this pass.
    media_server_pending: int = 0
    # Pictures that could not be taken from Immich; they are tried again on the next pass.
    pictures_failed: list[str] = field(default_factory=list)
    # People of the albums read in this pass: name as written for the media server -> Immich id.
    people: dict[str, UUID] = field(default_factory=dict)
    # Albums whose files could not all be written; their stamps are not moved on.
    failed_albums: set[UUID] = field(default_factory=set)

    @property
    def ok(self) -> bool:
        return not self.held and not self.errors


@dataclass(frozen=True)
class Output:
    """A target and where its files go. Without an executor nothing is written (a dry run).
    With `notify`, the shows whose files changed are queued for its media server."""

    target: Target
    executor: Executor | None
    notify: bool = False


@dataclass
class ImmichView:
    """What the albums of Immich should look like as shows, read once for all targets."""

    albums: int = 0
    visible: frozenset[UUID] = field(default_factory=frozenset)
    shows: list[tuple[Show, str]] = field(default_factory=list)
    untouched: set[UUID] = field(default_factory=set)
    hidden: set[UUID] = field(default_factory=set)
    folders: dict[UUID, str] = field(default_factory=dict)
    read: list[Album] = field(default_factory=list)
    skipped: list[tuple[str, Skipped]] = field(default_factory=list)
    people: dict[str, UUID] = field(default_factory=dict)


async def read_immich(
    immich: ImmichClient,
    registry: Registry,
    options: Options,
    *,
    full: bool,
    record_shows: bool,
) -> ImmichView:
    """Read the albums and build their shows. A quick pass (`full=False`) leaves alone the albums
    that have not changed since their files were last written. With `record_shows`, a new album
    gets its row (and so its folder name) in the registry."""
    view = ImmichView()
    albums = await immich.albums()
    rows = await registry.shows()
    view.albums = len(albums)
    view.visible = frozenset(album.id for album in albums)
    for album in albums:
        row = rows.get(album.id)
        if (
            row is not None
            and not full
            and _unchanged(album, row.album_updated_at, row.assets_modified_at)
        ):
            view.untouched.add(album.id)
            view.folders[album.id] = row.folder_name
            continue
        if row is None and record_shows:
            row = await registry.add_show(album.id, album.album_name)
        folder = (
            row.folder_name if row is not None else show_folder_name(album.album_name, album.id)
        )
        view.folders[album.id] = folder
        view.read.append(album)
        if row is not None and row.hidden:
            # Hidden on the page: no files, as if the album were not shared.
            view.hidden.add(album.id)
            continue
        mode = SeasonMode(row.season_mode) if row is not None else options.season_mode
        videos = [video async for video in immich.album_videos(album.id)]
        show = build_show(
            album,
            videos,
            replace(options, season_mode=mode),
            await registry.episode_edits(album.id) if row is not None else {},
            Registry.show_edit(row) if row is not None else None,
        )
        view.skipped.extend((album.album_name, item) for item in show.skipped)
        for episode in show.episodes:
            view.people.update((person.name, person.id) for person in episode.people)
        view.shows.append((show, folder))
    return view


async def apply_output(
    view: ImmichView,
    output: Output,
    *,
    immich: ImmichClient,
    registry: Registry,
    force: bool = False,
    pictures: dict[ImageSource, bytes] | None = None,
) -> SyncReport:
    """Bring the output folder of one target in line with `view`. Nothing is committed here.
    `pictures` keeps what was downloaded for one target, so that another takes it from there."""
    name = output.target.name
    report = SyncReport(
        dry_run=output.executor is None,
        target=name,
        albums=view.albums,
        albums_read=len(view.read),
        skipped=list(view.skipped),
        visible_albums=view.visible,
        people=dict(view.people),
    )
    desired: list[DesiredFile] = []
    for show, folder in view.shows:
        desired.extend(output.target.files(show, folder))
    plan = make_plan(
        desired,
        await registry.entries(name),
        untouched_albums=view.untouched,
        removed_on_purpose=view.hidden,
    )
    report.plan = plan
    report.changed_folders = {
        album_id: view.folders[album_id]
        for album_id in plan.changed_albums
        if album_id in view.folders
    }
    report.gone_albums = frozenset(plan.changed_albums - view.folders.keys())
    if plan.is_mass_removal and not force:
        report.held = True
        log.error(
            "%s: the sync would remove %d of %d links and was not carried out",
            name,
            plan.links_removed,
            plan.links_before,
        )
        return report
    executor = output.executor
    if executor is None:
        return report

    cache = {} if pictures is None else pictures
    actions = await _with_pictures(immich, plan.actions, report, cache)
    executor.ensure_marker()
    for action in actions:
        try:
            outcome = executor.apply(action)
        except (UnsafePathError, OSError) as exc:
            report.failed_albums.add(action.album_id)
            report.errors.append(f"{name}: {action.type.value} {action.path}: {exc}")
            log.error("%s: %s %s failed: %s", name, action.type.value, action.path, exc)
            continue
        if outcome.result is Result.FOREIGN:
            report.foreign.append(outcome)
            log.warning("%s: %s: %s; left alone", name, action.path, outcome.detail)
        if outcome.forget:
            await registry.forget(action.path, name)
        elif outcome.record and action.desired is not None:
            await registry.record(action.desired, name)
        if outcome.result is Result.DONE:
            if action.type is ActionType.CREATE:
                report.created += 1
            elif action.type is ActionType.REPLACE:
                report.replaced += 1
            else:
                report.removed += 1
    if output.notify:
        await registry.mark_pending(plan.changed_albums, name)
    return report


async def finish_pass(view: ImmichView, registry: Registry, reports: Sequence[SyncReport]) -> None:
    """Remember the people and how the albums looked, then commit everything the targets wrote.
    When a target held a mass removal, no album is stamped: the next quick pass must look at
    them all again."""
    await registry.remember_people(view.people)
    if not any(report.held for report in reports):
        failed = set().union(*(report.failed_albums for report in reports))
        for album in view.read:
            if album.id not in failed:
                await registry.set_stamps(
                    album.id, album.updated_at, album.last_modified_asset_timestamp
                )
    await registry.commit()


async def sync_outputs(
    *,
    immich: ImmichClient,
    registry: Registry,
    outputs: Sequence[Output],
    options: Options,
    full: bool = True,
    force: bool = False,
) -> list[SyncReport]:
    """One pass for every output. A dry run (no output has an executor) writes nothing, neither
    to the disks nor to the database."""
    writes = any(output.executor is not None for output in outputs)
    view = await read_immich(immich, registry, options, full=full, record_shows=writes)
    pictures: dict[ImageSource, bytes] = {}
    reports = [
        await apply_output(
            view, output, immich=immich, registry=registry, force=force, pictures=pictures
        )
        for output in outputs
    ]
    if writes:
        await finish_pass(view, registry, reports)
    return reports


async def run_sync(
    *,
    immich: ImmichClient,
    registry: Registry,
    executor: Executor | None,
    target: Target,
    options: Options,
    full: bool = True,
    force: bool = False,
    notify_media_server: bool = False,
) -> SyncReport:
    """One pass for a single target; see `sync_outputs`."""
    (report,) = await sync_outputs(
        immich=immich,
        registry=registry,
        outputs=[Output(target, executor, notify_media_server)],
        options=options,
        full=full,
        force=force,
    )
    return report


async def _with_pictures(
    immich: ImmichClient,
    actions: tuple[Action, ...],
    report: SyncReport,
    pictures: dict[ImageSource, bytes],
) -> list[Action]:
    """Download the pictures that have to be written, before anything is written.

    A picture Immich can not give is left out of this pass and noted; it is tried again on the
    next one. When Immich does not answer at all, the pass stops here, before any change."""
    result: list[Action] = []
    for action in actions:
        desired = action.desired
        if desired is None or desired.image is None or action.type is ActionType.REMOVE:
            result.append(action)
            continue
        content = pictures.get(desired.image)
        if content is None:
            try:
                if desired.image.of_person:
                    content = await immich.person_picture(desired.image.asset_id)
                else:
                    content = await immich.preview(desired.image.asset_id)
            except (ImmichUnreachableError, ImmichAuthError):
                raise
            except ImmichError as exc:
                report.pictures_failed.append(f"{action.path}: {exc}")
                log.warning("picture %s not taken from Immich: %s", action.path, exc)
                continue
            pictures[desired.image] = content
        result.append(replace(action, desired=replace(desired, content=content)))
    return result


def _unchanged(album: Album, updated_at: object, assets_modified_at: object) -> bool:
    return (
        updated_at is not None
        and album.updated_at == updated_at
        and album.last_modified_asset_timestamp == assets_modified_at
    )
