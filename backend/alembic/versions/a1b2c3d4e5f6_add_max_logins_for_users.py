"""add max logins for users

Revision ID: a1b2c3d4e5f6
Revises: 0f7118ad11ee
Create Date: 2026-06-30 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "0f7118ad11ee"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # max_logins: max simultaneous logins/devices per config.
    # 1 = single login (default), 0 = unlimited.
    op.add_column(
        "users",
        sa.Column(
            "max_logins",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "max_logins")
