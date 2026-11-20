# SPDX-License-Identifier: AGPL-3.0-or-later
"""Slideshows: the CLIP embedding of each photo, and the model it was made with.

Revision ID: 0014
Revises: 0013
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("photo_look", sa.Column("embedding", sa.LargeBinary(), nullable=True))
    op.add_column("photo_look", sa.Column("embedding_model", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("photo_look", "embedding_model")
    op.drop_column("photo_look", "embedding")
