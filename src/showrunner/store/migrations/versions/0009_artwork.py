# SPDX-License-Identifier: AGPL-3.0-or-later
"""Artwork: what was learned about the frames of videos, and the style of each show.

Revision ID: 0009
Revises: 0008
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "frame_look",
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("checksum", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("looks", JSONB(), nullable=False),
        sa.Column("failed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column(
            "analysed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("asset_id", name="pk_frame_look"),
    )
    op.create_table(
        "artwork",
        sa.Column(
            "album_id",
            sa.Uuid(),
            sa.ForeignKey("show.album_id", name="fk_artwork_album_id_show"),
            nullable=False,
        ),
        sa.Column("style_id", sa.String(48), nullable=False),
        sa.Column("seed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("frozen", sa.String(8), server_default="none", nullable=False),
        sa.PrimaryKeyConstraint("album_id", name="pk_artwork"),
    )


def downgrade() -> None:
    op.drop_table("artwork")
    op.drop_table("frame_look")
