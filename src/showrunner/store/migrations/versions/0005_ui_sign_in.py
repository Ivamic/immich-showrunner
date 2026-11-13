# SPDX-License-Identifier: AGPL-3.0-or-later
"""Signing in to the web page.

Revision ID: 0005
Revises: 0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ui_user",
        sa.Column("immich_user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("write_key_encrypted", sa.Text(), nullable=True),
        sa.Column("can_write", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("immich_user_id", name="pk_ui_user"),
    )
    op.create_table(
        "ui_session",
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("immich_user_id", sa.Uuid(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["immich_user_id"],
            ["ui_user.immich_user_id"],
            name="fk_ui_session_immich_user_id_ui_user",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("token_hash", name="pk_ui_session"),
    )


def downgrade() -> None:
    op.drop_table("ui_session")
    op.drop_table("ui_user")
