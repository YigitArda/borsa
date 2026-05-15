"""Add self-improving research state tables

Revision ID: 0018
Revises: 0017
Create Date: 2026-05-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mutation_memory",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("feature_name", sa.String(length=100), nullable=False),
        sa.Column("mutation_type", sa.String(length=50), nullable=False),
        sa.Column("score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("n_trials", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_updated", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("feature_name", "mutation_type", name="uq_mutation_memory_feature_type"),
    )
    op.create_index("ix_mutation_memory_feature_name", "mutation_memory", ["feature_name"])
    op.create_index("ix_mutation_memory_mutation_type", "mutation_memory", ["mutation_type"])

    op.create_table(
        "hyperparam_trials",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("strategy_id", sa.Integer(), nullable=True),
        sa.Column("study_name", sa.String(length=200), nullable=False),
        sa.Column("trial_number", sa.Integer(), nullable=False),
        sa.Column("params_json", sa.JSON(), nullable=False),
        sa.Column("sharpe", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="completed"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("study_name", "trial_number", name="uq_hyperparam_trials_study_trial"),
    )
    op.create_index("ix_hyperparam_trials_strategy_id", "hyperparam_trials", ["strategy_id"])
    op.create_index("ix_hyperparam_trials_study_name", "hyperparam_trials", ["study_name"])
    op.create_index("ix_hyperparam_trials_status", "hyperparam_trials", ["status"])

    op.create_table(
        "meta_learner_training_data",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("strategy_id", sa.Integer(), nullable=False),
        sa.Column("features_json", sa.JSON(), nullable=False),
        sa.Column("label", sa.Integer(), nullable=False),
        sa.Column("paper_hit_rate", sa.Float(), nullable=True),
        sa.Column("meta_confidence", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("strategy_id", name="uq_meta_learner_training_strategy"),
    )
    op.create_index("ix_meta_learner_training_data_strategy_id", "meta_learner_training_data", ["strategy_id"])
    op.create_index("ix_meta_learner_training_data_label", "meta_learner_training_data", ["label"])

    op.create_table(
        "strategy_bandit_arms",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("strategy_id", sa.Integer(), nullable=False),
        sa.Column("alpha", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("beta", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("last_updated", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("strategy_id", name="uq_strategy_bandit_arms_strategy"),
    )
    op.create_index("ix_strategy_bandit_arms_strategy_id", "strategy_bandit_arms", ["strategy_id"])

    op.create_table(
        "rl_agent_qtable",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("agent_name", sa.String(length=100), nullable=False),
        sa.Column("qtable_json", sa.JSON(), nullable=False),
        sa.Column("epsilon", sa.Float(), nullable=False, server_default="0.30"),
        sa.Column("steps", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_updated", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_name", name="uq_rl_agent_qtable_agent"),
    )
    op.create_index("ix_rl_agent_qtable_agent_name", "rl_agent_qtable", ["agent_name"])

    op.create_table(
        "research_trial_budgets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("budget_date", sa.Date(), nullable=False),
        sa.Column("iterations_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_iterations", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("budget_date", name="uq_research_trial_budgets_date"),
    )
    op.create_index("ix_research_trial_budgets_budget_date", "research_trial_budgets", ["budget_date"])


def downgrade() -> None:
    op.drop_index("ix_research_trial_budgets_budget_date", table_name="research_trial_budgets")
    op.drop_table("research_trial_budgets")
    op.drop_index("ix_rl_agent_qtable_agent_name", table_name="rl_agent_qtable")
    op.drop_table("rl_agent_qtable")
    op.drop_index("ix_strategy_bandit_arms_strategy_id", table_name="strategy_bandit_arms")
    op.drop_table("strategy_bandit_arms")
    op.drop_index("ix_meta_learner_training_data_label", table_name="meta_learner_training_data")
    op.drop_index("ix_meta_learner_training_data_strategy_id", table_name="meta_learner_training_data")
    op.drop_table("meta_learner_training_data")
    op.drop_index("ix_hyperparam_trials_status", table_name="hyperparam_trials")
    op.drop_index("ix_hyperparam_trials_study_name", table_name="hyperparam_trials")
    op.drop_index("ix_hyperparam_trials_strategy_id", table_name="hyperparam_trials")
    op.drop_table("hyperparam_trials")
    op.drop_index("ix_mutation_memory_mutation_type", table_name="mutation_memory")
    op.drop_index("ix_mutation_memory_feature_name", table_name="mutation_memory")
    op.drop_table("mutation_memory")
