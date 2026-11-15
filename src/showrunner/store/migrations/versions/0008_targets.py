# SPDX-License-Identifier: AGPL-3.0-or-later
"""Several targets: every file belongs to a target, and every target has its own queue of shows
the media server still has to be told about. What there was belongs to Jellyfin.

Revision ID: 0008
Revises: 0007
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "file",
        sa.Column("target", sa.String(16), server_default="jellyfin", nullable=False),
    )
    op.drop_constraint("pk_file", "file", type_="primary")
    op.create_primary_key("pk_file", "file", ["target", "path"])

    op.create_table(
        "media_server_pending",
        sa.Column("target", sa.String(16), nullable=False),
        sa.Column(
            "album_id",
            sa.Uuid(),
            sa.ForeignKey("show.album_id", name="fk_media_server_pending_album_id_show"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("target", "album_id", name="pk_media_server_pending"),
    )
    op.execute(
        "INSERT INTO media_server_pending (target, album_id) "
        "SELECT 'jellyfin', album_id FROM show WHERE media_server_pending"
    )
    op.drop_column("show", "media_server_pending")


def downgrade() -> None:
    op.add_column(
        "show",
        sa.Column("media_server_pending", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.execute(
        "UPDATE show SET media_server_pending = true WHERE album_id IN "
        "(SELECT album_id FROM media_server_pending WHERE target = 'jellyfin')"
    )
    op.drop_table("media_server_pending")
    op.execute("DELETE FROM file WHERE target <> 'jellyfin'")
    op.drop_constraint("pk_file", "file", type_="primary")
    op.create_primary_key("pk_file", "file", ["path"])
    op.drop_column("file", "target")
