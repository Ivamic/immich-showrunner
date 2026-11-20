# SPDX-License-Identifier: AGPL-3.0-or-later
"""Slideshows: what was learned about the photos of the albums.

Revision ID: 0013
Revises: 0012
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "photo_look",
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("checksum", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("look", JSONB(), nullable=False),
        sa.Column("failed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column(
            "analysed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("asset_id", name="pk_photo_look"),
    )


def downgrade() -> None:
    op.drop_table("photo_look")
