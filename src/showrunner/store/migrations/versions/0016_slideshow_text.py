# SPDX-License-Identifier: AGPL-3.0-or-later
"""The text of slideshows: its language, and the places under the title (for all and for each
album); slideshows on unless switched off (a row saved before keeps its choice).

Revision ID: 0016
Revises: 0015
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "slideshow_setting",
        sa.Column("language", sa.String(8), server_default="en", nullable=False),
    )
    op.add_column(
        "slideshow_setting",
        sa.Column("places", sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    op.add_column("album_slideshow", sa.Column("places", sa.Boolean(), nullable=True))
    op.alter_column("slideshow_setting", "enabled", server_default=sa.true())


def downgrade() -> None:
    op.alter_column("slideshow_setting", "enabled", server_default=sa.false())
    op.drop_column("album_slideshow", "places")
    op.drop_column("slideshow_setting", "places")
    op.drop_column("slideshow_setting", "language")
