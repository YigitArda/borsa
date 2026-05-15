"""Add equity_curve to walk_forward_results

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-15

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("walk_forward_results", sa.Column("equity_curve", sa.JSON, nullable=True))


def downgrade() -> None:
    op.drop_column("walk_forward_results", "equity_curve")
