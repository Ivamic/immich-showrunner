# SPDX-License-Identifier: AGPL-3.0-or-later
"""People the app wrote into metadata: the name for the media server and the person in Immich.

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "person",
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("immich_id", sa.Uuid(), nullable=False),
        sa.Column(
            "seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("name", name="pk_person"),
    )


def downgrade() -> None:
    op.drop_table("person")
