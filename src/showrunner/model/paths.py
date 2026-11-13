# SPDX-License-Identifier: AGPL-3.0-or-later
"""From the path of a file as Immich reports it to the path where the media server sees it."""

from collections.abc import Sequence
from pathlib import PurePosixPath

from showrunner.config import PathMapping


def map_path(original_path: str, mappings: Sequence[PathMapping]) -> PurePosixPath | None:
    """The target of the link for `original_path`, or None when no mapping covers it.

    Only an absolute path without `..` is accepted, and the result always stays inside the target
    of the mapping: a strange path from the API can not make a link point somewhere else."""
    path = PurePosixPath(original_path)
    if not path.is_absolute() or ".." in path.parts:
        return None
    for mapping in mappings:  # longest source first
        if path.is_relative_to(mapping.source) and path != mapping.source:
            return mapping.target / path.relative_to(mapping.source)
    return None
