# SPDX-License-Identifier: AGPL-3.0-or-later
from pathlib import Path, PurePosixPath

from showrunner.sync.executor import MARKER_NAME, MARKER_TEXT, Executor


def test_marker_is_created_once_and_never_overwritten(tmp_path: Path) -> None:
    executor = Executor(tmp_path, [PurePosixPath("/mnt/immich")])
    executor.ensure_marker()
    marker = tmp_path / MARKER_NAME
    assert marker.read_bytes() == MARKER_TEXT

    marker.write_bytes(b"edited by hand")
    executor.ensure_marker()
    assert marker.read_bytes() == b"edited by hand"


def test_marker_does_not_replace_a_folder(tmp_path: Path) -> None:
    (tmp_path / MARKER_NAME).mkdir()
    Executor(tmp_path, [PurePosixPath("/mnt/immich")]).ensure_marker()
    assert (tmp_path / MARKER_NAME).is_dir()
