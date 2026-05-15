"""
Weekly prediction generator — runs the promoted strategy against all stocks
and writes ranked predictions to weekly_predictions table.
"""
import logging
from datetime import date

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.config import settings
from app.models.strategy import Strategy
from app.models.stock import Stock
from app.models.prediction import WeeklyPrediction
from app.services.model_training import ModelTrainer

logger = logging.getLogger(__name__)


class WeeklyPredictionService:
    def __init__(self, session: Session):
        self.session = session

    def generate(self, tickers: list[str] | None = None, week_starting: date | None = None) -> int:
        tickers = tickers or settings.mvp_tickers
        week_starting = week_starting or date.today()

        # Get best promoted strategy
        strategies = self.session.execute(
            select(Strategy).where(Strategy.status == "promoted").order_by(Strategy.created_at.desc())
        ).scalars().all()

        if not strategies:
            logger.warning("No promoted strategy found; skipping prediction generation")
            return 0

        strategy = strategies[0]
        trainer = ModelTrainer(self.session, strategy.config)

        df = trainer.load_dataset(tickers)
        if df.empty:
            return 0

        # Get the most recent week available
        latest_week = df["week_ending"].max()
        latest_rows = df[df["week_ending"] == latest_week]

        feature_cols = [c for c in strategy.config.get("features", []) if c in latest_rows.columns]
        if not feature_cols:
            feature_cols = [c for c in latest_rows.columns if c not in ["stock_id", "week_ending", "label", "ticker"]]

        # Train final model on all data except latest week
        train_df = df[df["week_ending"] < latest_week]
        if len(train_df) < 100:
            return 0

        model, scaler = trainer._train(train_df)

        X = latest_rows[feature_cols].fillna(0).values
        probs = model.predict_proba(scaler.transform(X))[:, 1]

        # Build prediction rows
        rows = []
        for i, (_, row) in enumerate(latest_rows.iterrows()):
            prob = float(probs[i])
            confidence = "high" if prob >= 0.65 else "medium" if prob >= 0.5 else "low"
            rows.append({
                "stock_id": int(row["stock_id"]),
                "strategy_id": strategy.id,
                "week_starting": week_starting,
                "prob_2pct": prob,
                "prob_loss_2pct": None,
                "expected_return": None,
                "confidence": confidence,
                "rank": 0,
            })

        # Rank by probability
        rows.sort(key=lambda r: r["prob_2pct"], reverse=True)
        for rank, r in enumerate(rows, 1):
            r["rank"] = rank

        if not rows:
            return 0

        stmt = pg_insert(WeeklyPrediction).values(rows)
        stmt = stmt.on_conflict_do_nothing()
        self.session.execute(stmt)
        self.session.commit()
        logger.info(f"Generated {len(rows)} predictions for week {week_starting}")
        return len(rows)
