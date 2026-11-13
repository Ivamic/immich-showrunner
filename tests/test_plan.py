# SPDX-License-Identifier: AGPL-3.0-or-later
from pathlib import PurePosixPath
from uuid import UUID

import pytest

from showrunner.sync.plan import ActionType, DuplicatePathError, Entry, make_plan
from showrunner.targets.base import DesiredFile, FileKind

A1 = UUID("00000000-0000-4000-8000-0000000000a1")
A2 = UUID("00000000-0000-4000-8000-0000000000a2")


def asset(n: int) -> UUID:
    return UUID(f"{n:08x}-0000-4000-8000-000000000000")


def link(n: int, album: UUID = A1, target: str | None = None, folder: str = "show") -> DesiredFile:
    return DesiredFile(
        PurePosixPath(f"{folder}/Season 2024/v{n}.mp4"),
        FileKind.LINK,
        album,
        asset(n),
        link_target=PurePosixPath(target or f"/mnt/immich/v{n}.mp4"),
    )


def nfo(n: int, album: UUID = A1, content: bytes = b"<x/>", folder: str = "show") -> DesiredFile:
    return DesiredFile(
        PurePosixPath(f"{folder}/Season 2024/v{n}.nfo"),
        FileKind.EPISODE_NFO,
        album,
        asset(n),
        content=content,
    )


def recorded(file: DesiredFile) -> Entry:
    return Entry(
        file.path, file.kind, file.album_id, file.asset_id, file.link_target, file.content_hash
    )


def test_empty_registry_creates_everything() -> None:
    plan = make_plan([link(1), nfo(1)], [])
    assert [(a.type, str(a.path)) for a in plan.actions] == [
        (ActionType.CREATE, "show/Season 2024/v1.mp4"),
        (ActionType.CREATE, "show/Season 2024/v1.nfo"),
    ]
    assert plan.changed_albums == {A1}
    assert plan.links_before == 0 and plan.unchanged == 0


def test_nothing_changes_when_registry_matches() -> None:
    files = [link(1), nfo(1), link(2), nfo(2)]
    plan = make_plan(files, [recorded(f) for f in files])
    assert plan.is_empty
    assert plan.unchanged == 4
    assert plan.links_before == 2
    assert plan.changed_albums == frozenset()


def test_changed_target_and_changed_content_are_replaced() -> None:
    old = [link(1), nfo(1), link(2), nfo(2)]
    new = [link(1, target="/mnt/immich/moved/v1.mp4"), nfo(1), link(2), nfo(2, content=b"<y/>")]
    plan = make_plan(new, [recorded(f) for f in old])
    assert [(a.type, a.path.name) for a in plan.actions] == [
        (ActionType.REPLACE, "v1.mp4"),
        (ActionType.REPLACE, "v2.nfo"),
    ]
    replaced = plan.actions[0]
    assert replaced.entry is not None and replaced.desired is not None
    assert str(replaced.entry.link_target) == "/mnt/immich/v1.mp4"
    assert str(replaced.desired.link_target) == "/mnt/immich/moved/v1.mp4"


def test_video_left_the_album() -> None:
    old = [link(1), nfo(1), link(2), nfo(2)]
    plan = make_plan([link(1), nfo(1)], [recorded(f) for f in old])
    assert [(a.type, a.path.name) for a in plan.actions] == [
        (ActionType.REMOVE, "v2.mp4"),
        (ActionType.REMOVE, "v2.nfo"),
    ]
    assert plan.links_removed == 1
    assert all(a.desired is None and a.entry is not None for a in plan.actions)


def test_removals_come_first() -> None:
    old = [link(1), nfo(1)]
    plan = make_plan([link(2), nfo(2)], [recorded(f) for f in old])
    assert [a.type for a in plan.actions] == [
        ActionType.REMOVE,
        ActionType.REMOVE,
        ActionType.CREATE,
        ActionType.CREATE,
    ]


def test_untouched_album_is_left_alone() -> None:
    kept = [link(1, A2, folder="other"), nfo(1, A2, folder="other")]
    mine = [link(1), nfo(1)]
    plan = make_plan(mine, [recorded(f) for f in [*kept, *mine]], untouched_albums={A2})
    assert plan.is_empty
    assert plan.unchanged == 4
    # Without the mark, the same album would be removed: it is not in the desired state.
    assert make_plan(mine, [recorded(f) for f in [*kept, *mine]]).links_removed == 1


def test_untouched_album_with_desired_files_is_a_mistake() -> None:
    with pytest.raises(ValueError):
        make_plan([link(1, A2)], [], untouched_albums={A2})


def test_duplicate_path() -> None:
    with pytest.raises(DuplicatePathError):
        make_plan([link(1), link(1)], [])


def test_file_moved_to_another_album_is_replaced() -> None:
    plan = make_plan([link(1, A2)], [recorded(link(1, A1))])
    assert [a.type for a in plan.actions] == [ActionType.REPLACE]
    assert plan.changed_albums == {A2}


@pytest.mark.parametrize(
    ("before", "removed", "held"),
    [
        (100, 51, True),  # more than half and more than 20
        (100, 50, False),  # exactly half
        (30, 21, True),
        (30, 20, False),  # not more than 20
        (10, 10, False),  # a small library: an album that is no longer shared
        (1000, 400, False),  # many, but less than half
    ],
)
def test_mass_removal(before: int, removed: int, held: bool) -> None:
    registry = [recorded(link(n)) for n in range(before)]
    desired = [link(n) for n in range(removed, before)]
    plan = make_plan(desired, registry)
    assert plan.links_removed == removed
    assert plan.is_mass_removal is held
