"""move username_prefix from settings to admins (per-admin)

Revision ID: d8e9f0a1b2c3
Revises: c7d8e9f0a1b2
Create Date: 2026-07-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d8e9f0a1b2c3"
down_revision: Union[str, None] = "c7d8e9f0a1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("settings", "username_prefix")
    with op.batch_alter_table("admins") as batch_op:
        batch_op.add_column(sa.Column("username_prefix", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("admins") as batch_op:
        batch_op.drop_column("username_prefix")
    op.add_column("settings", sa.Column("username_prefix", sa.Text(), nullable=True))