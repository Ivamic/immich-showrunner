# SPDX-License-Identifier: AGPL-3.0-or-later
"""Carrying a plan out on the disk. The only module that creates and removes files.

The rules it keeps, whatever the plan says:

* it works only inside the output folder, and never through a link that leads out of it;
* it creates links only to the folders of the Immich library named in the path mappings, and never
  opens or changes what a link points to;
* it removes a link only if a link is still there, and a file only if it still holds what the app
  wrote; anything else at that path was put there by somebody else and is left alone;
* it never overwrites a file it did not write.
"""

import hashlib
import os
import secrets
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath

from showrunner.sync.plan import Action, ActionType
from showrunner.targets.base import FileKind

TEMP_PREFIX = ".showrunner-tmp-"


class Result(StrEnum):
    DONE = "done"
    # The file was already as it should be; the registry only has to learn about it.
    ADOPTED = "adopted"
    # The file was already gone; the registry only has to forget it.
    GONE = "gone"
    # Something that the app did not put there is at the path. Left alone; a removal still makes
    # the registry forget the path, a creation or replacement records nothing.
    FOREIGN = "foreign"


@dataclass(frozen=True)
class Outcome:
    action: Action
    result: Result
    detail: str = ""

    @property
    def record(self) -> bool:
        """The registry should now hold what the action wanted."""
        return self.action.type is not ActionType.REMOVE and self.result in (
            Result.DONE,
            Result.ADOPTED,
        )

    @property
    def forget(self) -> bool:
        """The registry should no longer hold the path."""
        return self.action.type is ActionType.REMOVE


class UnsafePathError(Exception):
    """A path would leave the output folder or a link would point outside the library."""


class Executor:
    def __init__(self, output_dir: Path, link_roots: Sequence[PurePosixPath]) -> None:
        """`output_dir` must exist. `link_roots` are the folders links may point into: the targets
        of the path mappings."""
        if not output_dir.is_dir():
            raise UnsafePathError(f"the output folder {str(output_dir)!r} does not exist")
        self._root = output_dir.resolve(strict=True)
        self._link_roots = tuple(link_roots)

    # --- paths --------------------------------------------------------------------------------

    def _locate(self, relative: PurePosixPath) -> Path:
        """The place of `relative` on the disk, after checking that no folder on the way is a link
        and that the place is inside the output folder."""
        if relative.is_absolute() or not relative.parts or ".." in relative.parts:
            raise UnsafePathError(f"not a path inside the output folder: {str(relative)!r}")
        current = self._root
        for part in relative.parts[:-1]:
            current = current / part
            if current.is_symlink():
                raise UnsafePathError(f"{str(current)!r} is a link; the app does not go through it")
            if current.exists() and not current.is_dir():
                raise UnsafePathError(f"{str(current)!r} is not a folder")
        path = current / relative.parts[-1]
        if not path.parent.resolve().is_relative_to(self._root):
            raise UnsafePathError(f"{str(path)!r} is outside the output folder")
        return path

    def _check_link_target(self, target: PurePosixPath) -> None:
        if not target.is_absolute() or ".." in target.parts:
            raise UnsafePathError(f"the target of a link must be absolute: {str(target)!r}")
        if not any(target.is_relative_to(root) and target != root for root in self._link_roots):
            raise UnsafePathError(f"{str(target)!r} is not inside the mapped Immich library")

    # --- actions ------------------------------------------------------------------------------

    def apply(self, action: Action) -> Outcome:
        path = self._locate(action.path)
        if action.type is ActionType.REMOVE:
            result, detail = self._remove(action, path)
        elif action.kind is FileKind.LINK:
            result, detail = self._put_link(action, path)
        else:
            result, detail = self._put_file(action, path)
        return Outcome(action, result, detail)

    def _put_link(self, action: Action, path: Path) -> tuple[Result, str]:
        assert action.desired is not None and action.desired.link_target is not None
        target = action.desired.link_target
        self._check_link_target(target)
        if path.is_symlink():
            if PurePosixPath(os.readlink(path)) == target:
                return Result.ADOPTED, ""
            if action.type is ActionType.CREATE:
                return Result.FOREIGN, "a link the app did not create is at this path"
            # A replacement: the link is ours, as the registry says. Swap it in one step.
            temp = path.with_name(TEMP_PREFIX + secrets.token_hex(6))
            os.symlink(str(target), temp)
            os.replace(temp, path)
            return Result.DONE, ""
        if path.exists():
            return Result.FOREIGN, "a file or folder is at this path, not a link"
        path.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(str(target), path)
        return Result.DONE, ""

    def _put_file(self, action: Action, path: Path) -> tuple[Result, str]:
        assert action.desired is not None and action.desired.content is not None
        content = action.desired.content
        if path.is_symlink() or (path.exists() and not path.is_file()):
            return Result.FOREIGN, "a link or folder is at this path, not a file"
        if path.exists():
            current = _hash(path)
            if current == action.desired.content_hash:
                return Result.ADOPTED, ""
            written_by_app = action.entry is not None and action.entry.content_hash == current
            if not written_by_app:
                return Result.FOREIGN, "the file was changed or created by somebody else"
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(TEMP_PREFIX + secrets.token_hex(6))
        try:
            temp.write_bytes(content)
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)
        return Result.DONE, ""

    def _remove(self, action: Action, path: Path) -> tuple[Result, str]:
        assert action.entry is not None
        if action.kind is FileKind.LINK:
            if path.is_symlink():
                path.unlink()
                self._prune(path.parent)
                return Result.DONE, ""
            if path.exists():
                return Result.FOREIGN, "a file or folder is at this path, not a link"
            self._prune(path.parent)
            return Result.GONE, ""
        if path.is_symlink() or (path.exists() and not path.is_file()):
            return Result.FOREIGN, "a link or folder is at this path, not a file"
        if not path.exists():
            self._prune(path.parent)
            return Result.GONE, ""
        if _hash(path) != action.entry.content_hash:
            return Result.FOREIGN, "the file was changed by somebody else"
        path.unlink()
        self._prune(path.parent)
        return Result.DONE, ""

    def _prune(self, folder: Path) -> None:
        """Remove `folder` and its parents while they are empty, up to the output folder, which
        always stays."""
        while folder != self._root and folder.is_relative_to(self._root):
            if folder.is_symlink() or not folder.is_dir():
                return
            try:
                folder.rmdir()  # fails when the folder is not empty
            except OSError:
                return
            folder = folder.parent


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
