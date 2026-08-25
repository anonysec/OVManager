# Copyright (c) 2025 anonysec. All rights reserved.
# Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

"""add per-node usage map for users

Revision ID: 5507b37a36d0
Revises: 1326f049eb10
Create Date: 2026-07-01 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5507b37a36d0"
down_revision: str | None = "1326f049eb10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # node_usage: JSON map {node_name: last_seen_cumulative_bytes} so traffic
    # deltas are tracked correctly per node when a user is on several nodes.
    op.add_column(
        "users",
        sa.Column("node_usage", sa.Text(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("users", "node_usage")
