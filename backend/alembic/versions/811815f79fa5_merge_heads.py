"""merge_heads

Revision ID: 811815f79fa5
Revises: c3d4e5f6a7b8, d4e5f6a7b8c9
Create Date: 2026-05-16 21:12:14.868013

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '811815f79fa5'
down_revision: Union[str, None] = ('c3d4e5f6a7b8', 'd4e5f6a7b8c9')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
