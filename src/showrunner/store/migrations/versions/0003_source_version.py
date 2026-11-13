# SPDX-License-Identifier: AGPL-3.0-or-later
"""The version of the Immich picture a file holds.

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("file", sa.Column("source_version", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("file", "source_version")
