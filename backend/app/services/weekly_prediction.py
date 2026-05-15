"""
Weekly prediction generator — runs the promoted strategy against all stocks
and writes ranked predictions to weekly_predictions table.

Generates three signals per stock:
  - prob_2pct: probability of >= 2% gain next week (main model)
  - prob_loss_2pct: probability of >= 2% loss next week (risk model)
  - expected_return: point estimate of next-week return (regression model)
  - signal_summary: top features driving the prediction
"""
import logging
from datetime import date

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.preprocessing import StandardScaler
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.config import settings
from app.models.strategy import Strategy
from app.models.stock import Stock
from app.models.prediction import WeeklyPrediction
from app.services.model_training import ModelTrainer
from app.services.calibration import CalibrationAnalyzer
from app.services.kill_switch import KillSwitchMonitor

logger = logging.getLogger(__name__)


def _train_risk_model(train_df: pd.DataFrame, feature_cols: list[str]):
    """Train a logistic regression risk model on risk_target_1w label."""
    if "risk_target_1w" not in train_df.columns:
        return None, None
    labeled = train_df.dropna(subset=["risk_target_1w"])
    if len(labeled) < 50:
        return None, None
    X = labeled[feature_cols].fillna(0).values
    y = labeled["risk_target_1w"].values
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    model = LogisticRegression(C=0.1, max_iter=1000, random_state=42, class_weight="balanced")
    model.fit(X_scaled, y)
    return model, scaler


def _train_return_model(train_df: pd.DataFrame, feature_cols: list[str]):
    """Train a ridge regression model on next_week_return label."""
    if "next_week_return" not in train_df.columns:
        return None, None
    labeled = train_df.dropna(subset=["next_week_return"])
    if len(labeled) < 50:
        return None, None
    X = labeled[feature_cols].fillna(0).values
    y = labeled["next_week_return"].values
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    model = Ridge(alpha=1.0)
    model.fit(X_scaled, y)
    return model, scaler


def _build_signal_summary(feature_cols: list[str], feature_values: np.ndarray, model) -> str:
    """Build a short text summary of the top features driving the prediction."""
    try:
        if hasattr(model, "coef_"):
            coef = model.coef_[0] if model.coef_.ndim > 1 else model.coef_
            contributions = coef * feature_values
            top_idx = np.argsort(np.abs(contributions))[::-1][:3]
            parts = []
            for idx in top_idx:
                fname = feature_cols[idx]
                fval = feature_values[idx]
                direction = "+" if contributions[idx] > 0 else "-"
                parts.append(f"{direction}{fname}={fval:.2f}")
            return ", ".join(parts)
        elif hasattr(model, "feature_importances_"):
            top_idx = np.argsort(model.feature_importances_)[::-1][:3]
            parts = []
            for idx in top_idx:
                fname = feature_cols[idx]
                fval = feature_values[idx]
                parts.append(f"{fname}={fval:.2f}")
            return ", ".join(parts)
    except Exception:
        pass
    return ""


class WeeklyPredictionService:
    def __init__(self, session: Session):
        self.session = session

    def generate(
        self,
        tickers: list[str] | None = None,
        week_starting: date | None = None,
        strategy_id: int | None = None,
    ) -> int:
        tickers = tickers or settings.mvp_tickers
        requested_week_starting = week_starting

        # Check kill switch before proceeding
        monitor = KillSwitchMonitor(self.session)
        if monitor.is_kill_switch_active():
            logger.warning("Kill switch is active; blocking prediction generation")
            return 0

        if strategy_id is not None:
            strategy = self.session.get(Strategy, strategy_id)
        else:
            strategy = self.session.execute(
                select(Strategy).where(Strategy.status == "promoted").order_by(Strategy.created_at.desc())
            ).scalars().first()

        if not strategy:
            logger.warning("No strategy found; skipping prediction generation")
            return 0

        trainer = ModelTrainer(self.session, strategy.config)

        df = trainer.load_dataset(tickers)
        if df.empty:
            return 0

        # Load labels too — needed for risk and return models
        from app.models.feature import LabelWeekly
        from app.models.stock import Stock as StockModel
        stocks = {
            s.ticker: s.id
            for s in self.session.execute(
                select(StockModel).where(StockModel.ticker.in_(tickers))
            ).scalars().all()
        }
        stock_ids = list(stocks.values())
        label_rows = self.session.execute(
            select(LabelWeekly).where(
                LabelWeekly.stock_id.in_(stock_ids),
                LabelWeekly.target_name.in_(["risk_target_1w", "next_week_return"]),
            )
        ).scalars().all()
        label_df = pd.DataFrame([{
            "stock_id": r.stock_id,
            "week_ending": pd.to_datetime(r.week_ending),
            "target_name": r.target_name,
            "value": r.value,
        } for r in label_rows])
        if not label_df.empty:
            label_pivot = label_df.pivot_table(
                index=["stock_id", "week_ending"],
                columns="target_name",
                values="value",
            ).reset_index()
            df = df.merge(label_pivot, on=["stock_id", "week_ending"], how="left")

        latest_week = df["week_ending"].max()
        latest_rows = df[df["week_ending"] == latest_week]
        train_df = df[df["week_ending"] < latest_week]
        week_starting = requested_week_starting or (latest_week + pd.Timedelta(days=3)).date()

        if len(train_df) < 100:
            return 0

        feature_cols = [c for c in strategy.config.get("features", []) if c in latest_rows.columns]
        if not feature_cols:
            feature_cols = [c for c in latest_rows.columns if c not in [
                "stock_id", "week_ending", "label", "ticker", "risk_target_1w", "next_week_return"
            ]]

        # Train main model
        main_model, main_scaler = trainer._train(train_df)

        # Train risk model (prob of loss)
        risk_model, risk_scaler = _train_risk_model(train_df, feature_cols)

        # Train return regression model
        return_model, return_scaler = _train_return_model(train_df, feature_cols)

        X_latest = latest_rows[feature_cols].fillna(0).values
        probs = main_model.predict_proba(main_scaler.transform(X_latest))[:, 1]

        risk_probs = None
        if risk_model is not None:
            risk_probs = risk_model.predict_proba(risk_scaler.transform(X_latest))[:, 1]

        expected_returns = None
        if return_model is not None:
            expected_returns = return_model.predict(return_scaler.transform(X_latest))

        # Fetch latest calibration for confidence adjustment
        analyzer = CalibrationAnalyzer(self.session)
        latest_cal = analyzer.get_latest_calibration(strategy.id)

        rows = []
        for i, (_, row) in enumerate(latest_rows.iterrows()):
            prob = float(probs[i])
            prob_loss = float(risk_probs[i]) if risk_probs is not None else None
            exp_ret = float(expected_returns[i]) if expected_returns is not None else None

            confidence, calibrated_prob = analyzer.adjust_confidence(prob, latest_cal)

            fvals = X_latest[i]
            summary = _build_signal_summary(feature_cols, fvals, main_model)

            rows.append({
                "stock_id": int(row["stock_id"]),
                "strategy_id": strategy.id,
                "week_starting": week_starting,
                "prob_2pct": calibrated_prob,
                "prob_loss_2pct": prob_loss,
                "expected_return": exp_ret,
                "confidence": confidence,
                "signal_summary": summary,
                "rank": 0,
            })

        rows.sort(key=lambda r: r["prob_2pct"], reverse=True)
        for rank, r in enumerate(rows, 1):
            r["rank"] = rank

        if not rows:
            return 0

        stmt = pg_insert(WeeklyPrediction).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["week_starting", "stock_id", "strategy_id"],
            set_={
                "prob_2pct": stmt.excluded.prob_2pct,
                "prob_loss_2pct": stmt.excluded.prob_loss_2pct,
                "expected_return": stmt.excluded.expected_return,
                "confidence": stmt.excluded.confidence,
                "rank": stmt.excluded.rank,
                "signal_summary": stmt.excluded.signal_summary,
            },
        )
        self.session.execute(stmt)
        self.session.commit()
        logger.info(f"Generated {len(rows)} predictions for week {week_starting}")
        return len(rows)
