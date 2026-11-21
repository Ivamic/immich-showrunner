# SPDX-License-Identifier: AGPL-3.0-or-later
"""Slideshows on the page: the settings, the choices for each album, the music switched off.

Revision ID: 0015
Revises: 0014
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "slideshow_setting",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("credits", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_slideshow_setting"),
    )
    op.create_table(
        "album_slideshow",
        sa.Column(
            "album_id",
            sa.Uuid(),
            sa.ForeignKey("show.album_id", name="fk_album_slideshow_album_id_show"),
            nullable=False,
        ),
        sa.Column("enabled", sa.Boolean(), nullable=True),
        sa.Column("mood", sa.String(16), nullable=True),
        sa.Column("music_seed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("auto_mood", sa.String(16), nullable=True),
        sa.Column("planned", JSONB(), server_default="[]", nullable=False),
        sa.PrimaryKeyConstraint("album_id", name="pk_album_slideshow"),
    )
    op.create_table(
        "music_setting",
        sa.Column("track_id", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.PrimaryKeyConstraint("track_id", name="pk_music_setting"),
    )


def downgrade() -> None:
    op.drop_table("music_setting")
    op.drop_table("album_slideshow")
    op.drop_table("slideshow_setting")
