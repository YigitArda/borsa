from datetime import datetime
from sqlalchemy import String, DateTime, Float, Integer, JSON, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class ModelRun(Base):
    __tablename__ = "model_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    strategy_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    model_type: Mapped[str] = mapped_column(String(50))
    fold: Mapped[int | None] = mapped_column(Integer)
    train_rows: Mapped[int | None] = mapped_column(Integer)
    test_rows: Mapped[int | None] = mapped_column(Integer)
    hyperparams: Mapped[dict | None] = mapped_column(JSON)
    metrics: Mapped[dict | None] = mapped_column(JSON)
    feature_importance: Mapped[dict | None] = mapped_column(JSON)
    model_path: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), default="completed")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class StrategyRule(Base):
    """Human-readable rules extracted from a strategy (for rule-based strategies)."""
    __tablename__ = "strategy_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    strategy_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    rule_type: Mapped[str] = mapped_column(String(50))   # entry | exit | filter
    description: Mapped[str] = mapped_column(Text)
    feature_name: Mapped[str | None] = mapped_column(String(100))
    operator: Mapped[str | None] = mapped_column(String(10))   # > < >= <= ==
    threshold: Mapped[float | None] = mapped_column(Float)
    importance: Mapped[float | None] = mapped_column(Float)


class SelectedStock(Base):
    """Stocks selected by the weekly pick engine."""
    __tablename__ = "selected_stocks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    week_starting: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    stock_id: Mapped[int] = mapped_column(Integer, nullable=False)
    strategy_id: Mapped[int] = mapped_column(Integer, nullable=False)
    rank: Mapped[int] = mapped_column(Integer)
    signal: Mapped[str | None] = mapped_column(String(30))    # BuyCandidate | Avoid
    confidence: Mapped[str | None] = mapped_column(String(20))
    risk_level: Mapped[str | None] = mapped_column(String(20))
    reasoning: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
