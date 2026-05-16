"""news article indexes for source and published_at queries

Revision ID: d4e5f6a7b8c9
Revises: 9a1b2c3d4e5f
Create Date: 2026-05-16 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "9a1b2c3d4e5f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_news_articles_source", "news_articles", ["source"], if_not_exists=True)
    op.create_index(
        "ix_news_articles_published_source",
        "news_articles",
        ["published_at", "source"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_news_articles_published_source", table_name="news_articles", if_exists=True)
    op.drop_index("ix_news_articles_source", table_name="news_articles", if_exists=True)
