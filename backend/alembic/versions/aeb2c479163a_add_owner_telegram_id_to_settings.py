# Copyright (c) 2025 anonysec. All rights reserved.
# Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

"""add owner_telegram_id to settings

Revision ID: aeb2c479163a
Revises: ab1e4ea97a4d
Create Date: 2026-07-23 00:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "aeb2c479163a"
down_revision: str | None = "ab1e4ea97a4d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("settings", sa.Column("owner_telegram_id", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("settings", "owner_telegram_id")
