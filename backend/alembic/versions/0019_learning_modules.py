"""Add tables for self-learning modules (katman.txt + new signal systems)

Revision ID: 0019
Revises: 0018
Create Date: 2026-05-15

Tables added:
  mutation_memory           — MutationScoreTracker (epsilon-greedy directed search)
  hyperparam_trials         — Optuna trial persistence
  meta_learner_training_data — MetaPromotionModel training examples
  strategy_bandit_arms      — Thompson Sampling Beta parameters per strategy
  rl_agent_qtable           — Q-Learning agent state
  arxiv_papers              — ArXiv paper scanner
  research_insights         — Claude-extracted feature ideas from papers
  signal_stacker_weights    — Regime-conditional stacker weights
"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # mutation_memory
    op.create_table(
        "mutation_memory",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("feature_name", sa.String(100), nullable=False),
        sa.Column("mutation_type", sa.String(50), nullable=False),
        sa.Column("score", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("n_trials", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_updated", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("feature_name", "mutation_type", name="uq_mutation_memory_feature_type"),
    )
    op.create_index("ix_mutation_memory_feature", "mutation_memory", ["feature_name"])
    op.create_index("ix_mutation_memory_type", "mutation_memory", ["mutation_type"])

    # hyperparam_trials
    op.create_table(
        "hyperparam_trials",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("strategy_id", sa.Integer(), nullable=True),
        sa.Column("study_name", sa.String(200), nullable=False),
        sa.Column("trial_number", sa.Integer(), nullable=False),
        sa.Column("params_json", postgresql.JSONB(), nullable=False),
        sa.Column("sharpe", sa.Float(), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="completed"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("study_name", "trial_number", name="uq_hyperparam_trials_study_trial"),
    )
    op.create_index("ix_hyperparam_trials_study", "hyperparam_trials", ["study_name"])
    op.create_index("ix_hyperparam_trials_status", "hyperparam_trials", ["status"])

    # meta_learner_training_data
    op.create_table(
        "meta_learner_training_data",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("strategy_id", sa.Integer(), nullable=False),
        sa.Column("features_json", postgresql.JSONB(), nullable=False),
        sa.Column("label", sa.Integer(), nullable=False),
        sa.Column("paper_hit_rate", sa.Float(), nullable=True),
        sa.Column("meta_confidence", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("strategy_id", name="uq_meta_learner_training_strategy"),
    )
    op.create_index("ix_meta_learner_strategy", "meta_learner_training_data", ["strategy_id"])
    op.create_index("ix_meta_learner_label", "meta_learner_training_data", ["label"])

    # strategy_bandit_arms
    op.create_table(
        "strategy_bandit_arms",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("strategy_id", sa.Integer(), nullable=False),
        sa.Column("alpha", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("beta", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("last_updated", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("strategy_id", name="uq_strategy_bandit_arms_strategy"),
    )
    op.create_index("ix_strategy_bandit_strategy", "strategy_bandit_arms", ["strategy_id"])

    # rl_agent_qtable
    op.create_table(
        "rl_agent_qtable",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agent_name", sa.String(100), nullable=False),
        sa.Column("qtable_json", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("epsilon", sa.Float(), nullable=False, server_default="0.3"),
        sa.Column("steps", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_updated", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("agent_name", name="uq_rl_agent_qtable_agent"),
    )
    op.create_index("ix_rl_agent_name", "rl_agent_qtable", ["agent_name"])

    # arxiv_papers
    op.create_table(
        "arxiv_papers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("arxiv_id", sa.String(50), nullable=False),
        sa.Column("url", sa.String(500), nullable=False),
        sa.Column("url_hash", sa.String(64), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("authors", sa.Text(), nullable=True),
        sa.Column("abstract", sa.Text(), nullable=True),
        sa.Column("published_date", sa.DateTime(), nullable=True),
        sa.Column("categories", sa.String(200), nullable=True),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("fetched_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("arxiv_id", name="uq_arxiv_papers_arxiv_id"),
        sa.UniqueConstraint("url_hash", name="uq_arxiv_papers_url_hash"),
    )
    op.create_index("ix_arxiv_papers_published", "arxiv_papers", ["published_date"])

    # research_insights
    op.create_table(
        "research_insights",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("paper_id", sa.Integer(), nullable=True),
        sa.Column("arxiv_id", sa.String(50), nullable=True),
        sa.Column("feature_name", sa.String(200), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("pseudocode", sa.Text(), nullable=True),
        sa.Column("applicable", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("status", sa.String(30), nullable=False, server_default="new"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_research_insights_arxiv", "research_insights", ["arxiv_id"])
    op.create_index("ix_research_insights_status", "research_insights", ["status"])

    # signal_stacker_weights
    op.create_table(
        "signal_stacker_weights",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("regime_type", sa.String(30), nullable=False),
        sa.Column("weights_json", postgresql.JSONB(), nullable=False),
        sa.Column("n_samples", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_trained", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("regime_type", name="uq_signal_stacker_regime"),
    )


def downgrade() -> None:
    op.drop_table("signal_stacker_weights")
    op.drop_table("research_insights")
    op.drop_table("arxiv_papers")
    op.drop_table("rl_agent_qtable")
    op.drop_table("strategy_bandit_arms")
    op.drop_table("meta_learner_training_data")
    op.drop_table("hyperparam_trials")
    op.drop_table("mutation_memory")
