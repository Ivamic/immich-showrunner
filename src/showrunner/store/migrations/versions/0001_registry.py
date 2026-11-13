# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shows and the registry of created files.

Revision ID: 0001
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "show",
        sa.Column("album_id", sa.Uuid(), nullable=False),
        sa.Column("folder_name", sa.Text(), nullable=False),
        sa.Column("season_mode", sa.String(16), server_default="year", nullable=False),
        sa.Column("album_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("assets_modified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("album_id", name="pk_show"),
        sa.UniqueConstraint("folder_name", name="uq_show_folder_name"),
    )
    op.create_table(
        "file",
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("album_id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=True),
        sa.Column("link_target", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["album_id"], ["show.album_id"], name="fk_file_album_id_show"),
        sa.PrimaryKeyConstraint("path", name="pk_file"),
    )
    op.create_index("ix_file_album_id", "file", ["album_id"])


def downgrade() -> None:
    op.drop_index("ix_file_album_id", table_name="file")
    op.drop_table("file")
    op.drop_table("show")
