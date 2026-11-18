# SPDX-License-Identifier: AGPL-3.0-or-later
"""Folders of shows without dates with separators in their names.

Jellyfin reads a date with separators anywhere in the path of an episode — `2026-06_07 - Trip`
in the folder of the show too — as the date of a daily episode, and takes every video of the
show for a version of one episode. The names of the folders lose the separators of their
dates, as the names of the files did (D-039); the next sync moves the files there.

Revision ID: 0010
Revises: 0009
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# A copy of the rule in showrunner.model.naming, as it was when this migration was written.
_DATE_YMD = re.compile(r"(\d{4})[._ -](\d{2})[._ -](\d{2})")
_DATE_DMY = re.compile(r"(\d{2})[._ -](\d{2})[._ -](\d{4})")


def undated(name: str) -> str:
    return _DATE_DMY.sub(r"\1\2\3", _DATE_YMD.sub(r"\1\2\3", name))


def upgrade() -> None:
    connection = op.get_bind()
    rows = connection.execute(sa.text("SELECT album_id, folder_name FROM show")).all()
    taken = {folder for _, folder in rows}
    for album_id, folder in rows:
        new = undated(folder)
        if new == folder or new in taken:
            continue
        connection.execute(
            sa.text("UPDATE show SET folder_name = :new WHERE album_id = :album"),
            {"new": new, "album": album_id},
        )
        taken.discard(folder)
        taken.add(new)


def downgrade() -> None:
    """The old names are not kept; the files stay where the last sync put them."""
