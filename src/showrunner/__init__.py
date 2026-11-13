# SPDX-License-Identifier: AGPL-3.0-or-later
"""Showrunner for Immich: Immich albums as TV shows in a media server, without copying files."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("showrunner")
except PackageNotFoundError:  # running from a source tree that is not installed
    __version__ = "0.0.0"

__all__ = ["__version__"]
