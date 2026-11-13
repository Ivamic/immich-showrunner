# SPDX-License-Identifier: AGPL-3.0-or-later
"""Edits made on the page: the title and visibility of a show, and of its episodes.

Revision ID: 0006
Revises: 0005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("show", sa.Column("title", sa.Text(), nullable=True))
    op.add_column(
        "show", sa.Column("hidden", sa.Boolean(), server_default=sa.false(), nullable=False)
    )
    op.create_table(
        "episode_edit",
        sa.Column("album_id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("plot", sa.Text(), nullable=True),
        sa.Column("sort_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hidden", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["album_id"], ["show.album_id"], name="fk_episode_edit_album_id_show"
        ),
        sa.PrimaryKeyConstraint("album_id", "asset_id", name="pk_episode_edit"),
    )


def downgrade() -> None:
    op.drop_table("episode_edit")
    op.drop_column("show", "hidden")
    op.drop_column("show", "title")
