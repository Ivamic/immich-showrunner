# SPDX-License-Identifier: AGPL-3.0-or-later
"""Choices about artwork made on the page: the cover of the album as the poster, frozen
pictures, and styles switched off.

Revision ID: 0011
Revises: 0010
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("artwork", sa.Column("frozen_jobs", JSONB(), nullable=True))
    op.add_column(
        "artwork", sa.Column("use_cover", sa.Boolean(), server_default=sa.false(), nullable=False)
    )
    op.create_table(
        "style_setting",
        sa.Column("style_id", sa.String(48), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.PrimaryKeyConstraint("style_id", name="pk_style_setting"),
    )


def downgrade() -> None:
    op.drop_table("style_setting")
    op.drop_column("artwork", "use_cover")
    op.drop_column("artwork", "frozen_jobs")
