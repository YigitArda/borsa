"""model promotion booleans and paper trade integrity

Revision ID: f3c9a6b7d8e1
Revises: 08d1c2d44a65
Create Date: 2026-05-16 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f3c9a6b7d8e1"
down_revision: Union[str, None] = "08d1c2d44a65"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("model_promotions") as batch_op:
        batch_op.alter_column(
            "outperforms_spy",
            existing_type=sa.String(length=5),
            type_=sa.Boolean(),
            existing_nullable=True,
            postgresql_using=(
                "CASE "
                "WHEN outperforms_spy IS NULL THEN NULL "
                "WHEN lower(outperforms_spy) IN ('true', '1', 't', 'yes', 'y') THEN TRUE "
                "ELSE FALSE END"
            ),
        )
        batch_op.alter_column(
            "concentration_ok",
            existing_type=sa.String(length=5),
            type_=sa.Boolean(),
            existing_nullable=True,
            postgresql_using=(
                "CASE "
                "WHEN concentration_ok IS NULL THEN NULL "
                "WHEN lower(concentration_ok) IN ('true', '1', 't', 'yes', 'y') THEN TRUE "
                "ELSE FALSE END"
            ),
        )

    with op.batch_alter_table("paper_trades") as batch_op:
        batch_op.create_check_constraint(
            "ck_paper_trades_closed_values",
            "(status != 'closed') OR (entry_price IS NOT NULL AND exit_price IS NOT NULL AND realized_return IS NOT NULL)",
        )


def downgrade() -> None:
    with op.batch_alter_table("paper_trades") as batch_op:
        batch_op.drop_constraint("ck_paper_trades_closed_values", type_="check")

    with op.batch_alter_table("model_promotions") as batch_op:
        batch_op.alter_column(
            "outperforms_spy",
            existing_type=sa.Boolean(),
            type_=sa.String(length=5),
            existing_nullable=True,
            postgresql_using=("CASE WHEN outperforms_spy THEN 'True' ELSE 'False' END"),
        )
        batch_op.alter_column(
            "concentration_ok",
            existing_type=sa.Boolean(),
            type_=sa.String(length=5),
            existing_nullable=True,
            postgresql_using=("CASE WHEN concentration_ok THEN 'True' ELSE 'False' END"),
        )
