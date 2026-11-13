# SPDX-License-Identifier: AGPL-3.0-or-later
"""The executor on a real file system. Links need Linux: on Windows these tests are skipped and
run in a container (and in CI)."""

import hashlib
import os
from pathlib import Path, PurePosixPath
from uuid import UUID

import pytest

from showrunner.sync.executor import Executor, Result, UnsafePathError
from showrunner.sync.plan import Action, ActionType, Entry
from showrunner.targets.base import DesiredFile, FileKind

pytestmark = pytest.mark.skipif(os.name == "nt", reason="symbolic links need Linux")

ALBUM = UUID("00000000-0000-4000-8000-0000000000a1")
LIBRARY = PurePosixPath("/mnt/immich")
REL_LINK = PurePosixPath("show/Season 2024/v1.mp4")
REL_NFO = PurePosixPath("show/Season 2024/v1.nfo")


@pytest.fixture
def out(tmp_path: Path) -> Path:
    folder = tmp_path / "output"
    folder.mkdir()
    return folder


@pytest.fixture
def executor(out: Path) -> Executor:
    return Executor(out, [LIBRARY])


def want_link(
    path: PurePosixPath = REL_LINK, target: str = "/mnt/immich/upload/v1.mp4"
) -> DesiredFile:
    return DesiredFile(path, FileKind.LINK, ALBUM, link_target=PurePosixPath(target))


def want_file(content: bytes = b"<x/>", path: PurePosixPath = REL_NFO) -> DesiredFile:
    return DesiredFile(path, FileKind.EPISODE_NFO, ALBUM, content=content)


def entry(file: DesiredFile) -> Entry:
    return Entry(
        file.path, file.kind, file.album_id, file.asset_id, file.link_target, file.content_hash
    )


def create(file: DesiredFile) -> Action:
    return Action(ActionType.CREATE, file.path, file.kind, ALBUM, file, None)


def replace(file: DesiredFile, old: DesiredFile) -> Action:
    return Action(ActionType.REPLACE, file.path, file.kind, ALBUM, file, entry(old))


def remove(old: DesiredFile) -> Action:
    return Action(ActionType.REMOVE, old.path, old.kind, ALBUM, None, entry(old))


def tree(root: Path) -> list[str]:
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))


# --- creating ---------------------------------------------------------------------------------


def test_create_link_and_file(executor: Executor, out: Path) -> None:
    link = executor.apply(create(want_link()))
    nfo = executor.apply(create(want_file()))
    assert (link.result, nfo.result) == (Result.DONE, Result.DONE)
    assert link.record and nfo.record
    path = out / REL_LINK
    assert path.is_symlink()
    assert os.readlink(path) == "/mnt/immich/upload/v1.mp4"
    assert (out / REL_NFO).read_bytes() == b"<x/>"
    assert not any(TEMP in name for name in tree(out))


TEMP = ".showrunner-tmp-"


def test_create_again_adopts(executor: Executor) -> None:
    executor.apply(create(want_link()))
    executor.apply(create(want_file()))
    assert executor.apply(create(want_link())).result is Result.ADOPTED
    assert executor.apply(create(want_file())).result is Result.ADOPTED


def test_create_does_not_overwrite_what_is_there(executor: Executor, out: Path) -> None:
    folder = out / "show" / "Season 2024"
    folder.mkdir(parents=True)
    (folder / "v1.mp4").write_bytes(b"a real video")
    (folder / "v1.nfo").write_bytes(b"written by hand")
    link = executor.apply(create(want_link()))
    nfo = executor.apply(create(want_file()))
    assert (link.result, nfo.result) == (Result.FOREIGN, Result.FOREIGN)
    assert not link.record and not nfo.record
    assert (folder / "v1.mp4").read_bytes() == b"a real video"
    assert (folder / "v1.nfo").read_bytes() == b"written by hand"


def test_create_does_not_take_over_a_foreign_link(executor: Executor, out: Path) -> None:
    folder = out / "show" / "Season 2024"
    folder.mkdir(parents=True)
    os.symlink("/somewhere/else.mp4", folder / "v1.mp4")
    assert executor.apply(create(want_link())).result is Result.FOREIGN
    assert os.readlink(folder / "v1.mp4") == "/somewhere/else.mp4"


# --- replacing --------------------------------------------------------------------------------


def test_replace_link_target(executor: Executor, out: Path) -> None:
    old = want_link()
    executor.apply(create(old))
    new = want_link(target="/mnt/immich/library/2024/v1.mp4")
    assert executor.apply(replace(new, old)).result is Result.DONE
    assert os.readlink(out / REL_LINK) == "/mnt/immich/library/2024/v1.mp4"
    assert tree(out) == ["show", "show/Season 2024", "show/Season 2024/v1.mp4"]


def test_replace_file_written_by_the_app(executor: Executor, out: Path) -> None:
    old = want_file(b"<old/>")
    executor.apply(create(old))
    assert executor.apply(replace(want_file(b"<new/>"), old)).result is Result.DONE
    assert (out / REL_NFO).read_bytes() == b"<new/>"


def test_replace_keeps_a_file_changed_by_hand(executor: Executor, out: Path) -> None:
    old = want_file(b"<old/>")
    executor.apply(create(old))
    (out / REL_NFO).write_bytes(b"<edited by hand/>")
    outcome = executor.apply(replace(want_file(b"<new/>"), old))
    assert outcome.result is Result.FOREIGN and not outcome.record
    assert (out / REL_NFO).read_bytes() == b"<edited by hand/>"


def test_replace_restores_a_missing_file_and_link(executor: Executor, out: Path) -> None:
    assert executor.apply(replace(want_file(b"<new/>"), want_file(b"<old/>"))).result is Result.DONE
    assert (
        executor.apply(replace(want_link(), want_link(target="/mnt/immich/x.mp4"))).result
        is Result.DONE
    )
    assert (out / REL_NFO).read_bytes() == b"<new/>"
    assert (out / REL_LINK).is_symlink()


def test_replace_link_does_not_touch_a_real_file(executor: Executor, out: Path) -> None:
    (out / "show" / "Season 2024").mkdir(parents=True)
    (out / REL_LINK).write_bytes(b"a real video")
    outcome = executor.apply(replace(want_link(), want_link(target="/mnt/immich/x.mp4")))
    assert outcome.result is Result.FOREIGN
    assert (out / REL_LINK).read_bytes() == b"a real video"


# --- removing ---------------------------------------------------------------------------------


def test_remove_cleans_up_empty_folders_but_not_the_output_folder(
    executor: Executor, out: Path
) -> None:
    executor.apply(create(want_link()))
    executor.apply(create(want_file()))
    first = executor.apply(remove(want_link()))
    assert first.result is Result.DONE and first.forget
    assert tree(out) == ["show", "show/Season 2024", "show/Season 2024/v1.nfo"]
    assert executor.apply(remove(want_file())).result is Result.DONE
    assert tree(out) == []
    assert out.is_dir()


def test_remove_keeps_folders_with_foreign_files(executor: Executor, out: Path) -> None:
    executor.apply(create(want_link()))
    (out / "show" / "poster.jpg").write_bytes(b"put here by hand")
    executor.apply(remove(want_link()))
    assert tree(out) == ["show", "show/poster.jpg"]


def test_remove_link_never_removes_the_video_it_points_to(tmp_path: Path, out: Path) -> None:
    library = tmp_path / "library"
    library.mkdir()
    video = library / "v1.mp4"
    video.write_bytes(b"the original")
    executor = Executor(out, [PurePosixPath(library.as_posix())])
    link = want_link(target=video.as_posix())
    executor.apply(create(link))
    assert (out / REL_LINK).read_bytes() == b"the original"
    assert executor.apply(remove(link)).result is Result.DONE
    assert not (out / REL_LINK).exists()
    assert video.read_bytes() == b"the original"


def test_remove_link_leaves_a_real_file(executor: Executor, out: Path) -> None:
    (out / "show" / "Season 2024").mkdir(parents=True)
    (out / REL_LINK).write_bytes(b"a real video")
    outcome = executor.apply(remove(want_link()))
    assert outcome.result is Result.FOREIGN and outcome.forget
    assert (out / REL_LINK).read_bytes() == b"a real video"


def test_remove_file_changed_by_hand_is_left(executor: Executor, out: Path) -> None:
    old = want_file(b"<old/>")
    executor.apply(create(old))
    (out / REL_NFO).write_bytes(b"<edited by hand/>")
    assert executor.apply(remove(old)).result is Result.FOREIGN
    assert (out / REL_NFO).read_bytes() == b"<edited by hand/>"


def test_remove_what_is_already_gone(executor: Executor) -> None:
    assert executor.apply(remove(want_link())).result is Result.GONE
    assert executor.apply(remove(want_file())).result is Result.GONE


# --- staying inside ---------------------------------------------------------------------------


def test_output_folder_must_exist(tmp_path: Path) -> None:
    with pytest.raises(UnsafePathError):
        Executor(tmp_path / "missing", [LIBRARY])


def test_does_not_go_through_a_folder_that_is_a_link(
    tmp_path: Path, executor: Executor, out: Path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "v1.nfo").write_bytes(hashlib.sha256(b"x").digest())
    os.symlink(outside, out / "show")
    for action in (
        create(want_file(path=PurePosixPath("show/v1.nfo"))),
        remove(want_file(path=PurePosixPath("show/v1.nfo"))),
        create(want_link(path=PurePosixPath("show/v2.mp4"))),
    ):
        with pytest.raises(UnsafePathError):
            executor.apply(action)
    assert tree(outside) == ["v1.nfo"]


def test_link_target_must_be_inside_the_library(executor: Executor, out: Path) -> None:
    for target in ("/etc/passwd", "/mnt/immich", "/mnt/immich-other/v.mp4"):
        with pytest.raises(UnsafePathError):
            executor.apply(create(want_link(target=target)))
    assert tree(out) == []


def test_action_with_a_path_outside_is_refused(executor: Executor) -> None:
    file = want_file()
    for bad in ("../escape.nfo", "/abs/escape.nfo", "a/../../escape.nfo"):
        action = Action(ActionType.CREATE, PurePosixPath(bad), file.kind, ALBUM, file, None)
        with pytest.raises(UnsafePathError):
            executor.apply(action)
