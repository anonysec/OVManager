# Copyright (c) 2025 anonysec. All rights reserved.
# Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

"""move username_prefix from settings to admins (per-admin)

Revision ID: ab1e4ea97a4d
Revises: c3ca3949fc25
Create Date: 2026-07-23 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ab1e4ea97a4d"
down_revision: str | None = "c3ca3949fc25"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("settings", "username_prefix")
    with op.batch_alter_table("admins") as batch_op:
        batch_op.add_column(sa.Column("username_prefix", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("admins") as batch_op:
        batch_op.drop_column("username_prefix")
    op.add_column("settings", sa.Column("username_prefix", sa.Text(), nullable=True))
