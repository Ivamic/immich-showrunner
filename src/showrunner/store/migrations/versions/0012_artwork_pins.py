# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pictures pinned one by one instead of the album frozen as a whole; other frames for a single
picture; the jobs last drawn, so that a pin keeps exactly what is shown.

A frozen album becomes pinned pictures: "all" pins every frozen picture, "show" those of the
show (not the posters of seasons). An album frozen but not drawn since has nothing to pin.

Revision ID: 0012
Revises: 0011
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _key(job: dict) -> str:  # type: ignore[type-arg]
    return job["kind"] if job.get("season") is None else f"{job['kind']}:{job['season']}"


def upgrade() -> None:
    for column in ("slot_seeds", "drawn_jobs", "pinned_jobs"):
        op.add_column(
            "artwork",
            sa.Column(column, JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        )
    connection = op.get_bind()
    rows = connection.execute(
        sa.text("SELECT album_id, frozen, frozen_jobs FROM artwork WHERE frozen <> 'none'")
    ).all()
    for album_id, frozen, jobs in rows:
        pinned = {
            _key(job): job for job in (jobs or []) if frozen == "all" or job.get("season") is None
        }
        connection.execute(
            sa.text("UPDATE artwork SET pinned_jobs = CAST(:p AS jsonb) WHERE album_id = :a"),
            {"p": json.dumps(pinned), "a": album_id},
        )
    op.drop_column("artwork", "frozen_jobs")
    op.drop_column("artwork", "frozen")


def downgrade() -> None:
    op.add_column(
        "artwork",
        sa.Column("frozen", sa.String(8), server_default="none", nullable=False),
    )
    op.add_column("artwork", sa.Column("frozen_jobs", JSONB(), nullable=True))
    for column in ("pinned_jobs", "drawn_jobs", "slot_seeds"):
        op.drop_column("artwork", column)
