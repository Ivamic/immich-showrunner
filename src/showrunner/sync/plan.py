# SPDX-License-Identifier: AGPL-3.0-or-later
"""What has to change in the output folder. Nothing here touches the disk.

The plan compares the files that should exist with the registry: the record of every file the app
has created. A file is only ever removed because the registry says the app created it."""

from collections.abc import Collection, Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import PurePosixPath
from uuid import UUID

from showrunner.targets.base import DesiredFile, FileKind

# A sync is held when it would remove more than this share of all links and more than this many:
# it looks like the wrong API key or user, not like albums that are no longer shared.
MASS_REMOVAL_SHARE = 0.5
MASS_REMOVAL_MIN = 20


@dataclass(frozen=True)
class Entry:
    """A file the app created, as the registry remembers it."""

    path: PurePosixPath
    kind: FileKind
    album_id: UUID
    asset_id: UUID | None = None
    link_target: PurePosixPath | None = None
    content_hash: str | None = None
    # For a picture: the version of the Immich picture it holds.
    source_version: str | None = None


class ActionType(StrEnum):
    CREATE = "create"
    REPLACE = "replace"  # the target of a link or the content of a file changed
    REMOVE = "remove"


@dataclass(frozen=True)
class Action:
    type: ActionType
    path: PurePosixPath
    kind: FileKind
    album_id: UUID
    # What to create or replace with; None for a removal.
    desired: DesiredFile | None = None
    # What the registry holds; None for a creation.
    entry: Entry | None = None


@dataclass(frozen=True)
class Plan:
    actions: tuple[Action, ...] = ()
    # Links recorded in the registry before this plan.
    links_before: int = 0
    unchanged: int = 0
    # Albums whose files change in any way: the media server has to be told about them.
    changed_albums: frozenset[UUID] = field(default_factory=frozenset)
    # Links removed because the user asked for it (a show hidden on the page): they do not count
    # towards a mass removal.
    links_removed_on_purpose: int = 0

    def of_type(self, action_type: ActionType) -> tuple[Action, ...]:
        return tuple(a for a in self.actions if a.type is action_type)

    @property
    def links_removed(self) -> int:
        return sum(
            1 for a in self.actions if a.type is ActionType.REMOVE and a.kind is FileKind.LINK
        )

    @property
    def is_empty(self) -> bool:
        return not self.actions

    @property
    def is_mass_removal(self) -> bool:
        unexpected = self.links_removed - self.links_removed_on_purpose
        return unexpected > MASS_REMOVAL_MIN and unexpected > self.links_before * MASS_REMOVAL_SHARE


class DuplicatePathError(ValueError):
    """Two files of the desired state have the same path."""


def make_plan(
    desired: Iterable[DesiredFile],
    registry: Iterable[Entry],
    *,
    untouched_albums: Collection[UUID] = (),
    removed_on_purpose: Collection[UUID] = (),
) -> Plan:
    """Compare what should exist with what the registry holds.

    `untouched_albums` are albums that were not read from Immich this time because nothing in
    them changed: their files are left as they are."""
    wanted: dict[PurePosixPath, DesiredFile] = {}
    for file in desired:
        if file.path in wanted:
            raise DuplicatePathError(str(file.path))
        if file.album_id in untouched_albums:
            raise ValueError(f"album {file.album_id} is both untouched and has desired files")
        wanted[file.path] = file

    actions: list[Action] = []
    unchanged = 0
    links_before = 0
    recorded: set[PurePosixPath] = set()
    for entry in registry:
        recorded.add(entry.path)
        if entry.kind is FileKind.LINK:
            links_before += 1
        if entry.album_id in untouched_albums:
            unchanged += 1
            continue
        want = wanted.get(entry.path)
        if want is None:
            actions.append(
                Action(ActionType.REMOVE, entry.path, entry.kind, entry.album_id, None, entry)
            )
        elif _same(want, entry):
            unchanged += 1
        else:
            actions.append(
                Action(ActionType.REPLACE, want.path, want.kind, want.album_id, want, entry)
            )

    for path, want in wanted.items():
        if path not in recorded:
            actions.append(Action(ActionType.CREATE, path, want.kind, want.album_id, want, None))

    # Removals first, deepest paths first, so that a path freed by one show can be taken by
    # another; then everything else in the order of the paths.
    actions.sort(key=lambda a: (a.type is not ActionType.REMOVE, str(a.path)))
    return Plan(
        actions=tuple(actions),
        links_before=links_before,
        unchanged=unchanged,
        changed_albums=frozenset(a.album_id for a in actions),
        links_removed_on_purpose=sum(
            1
            for a in actions
            if a.type is ActionType.REMOVE
            and a.kind is FileKind.LINK
            and a.album_id in removed_on_purpose
        ),
    )


def _same(want: DesiredFile, entry: Entry) -> bool:
    if want.kind is not entry.kind or (want.album_id, want.asset_id) != (
        entry.album_id,
        entry.asset_id,
    ):
        return False
    if want.kind is FileKind.IMAGE:
        # The picture is not downloaded to compare it: its version in Immich tells.
        return want.source_version == entry.source_version
    return want.link_target == entry.link_target and want.content_hash == entry.content_hash
