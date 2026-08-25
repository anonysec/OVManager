# Copyright (c) 2025 anonysec. All rights reserved.
# Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

"""add username_prefix, telegram_id, bot_config to settings

Revision ID: c3ca3949fc25
Revises: 5507b37a36d0
Create Date: 2026-07-22 23:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3ca3949fc25"
down_revision: str | None = "5507b37a36d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("settings", sa.Column("username_prefix", sa.Text(), nullable=True))
    op.add_column("settings", sa.Column("bot_token", sa.Text(), nullable=True))
    op.add_column("settings", sa.Column("bot_enabled", sa.Boolean(), nullable=False, server_default="0"))
    op.add_column("settings", sa.Column("default_days", sa.Integer(), nullable=False, server_default="30"))
    op.add_column("settings", sa.Column("default_traffic_gb", sa.Integer(), nullable=False, server_default="100"))
    op.add_column("settings", sa.Column("default_max_users", sa.Integer(), nullable=False, server_default="1"))
    with op.batch_alter_table("admins") as batch_op:
        batch_op.add_column(sa.Column("telegram_id", sa.BigInteger(), nullable=True))
        batch_op.create_unique_constraint("uq_admins_telegram_id", ["telegram_id"])


def downgrade() -> None:
    with op.batch_alter_table("admins") as batch_op:
        batch_op.drop_constraint("uq_admins_telegram_id", type_="unique")
        batch_op.drop_column("telegram_id")
    op.drop_column("settings", "default_max_users")
    op.drop_column("settings", "default_traffic_gb")
    op.drop_column("settings", "default_days")
    op.drop_column("settings", "bot_enabled")
    op.drop_column("settings", "bot_token")
    op.drop_column("settings", "username_prefix")
