"""
LightGBM model training with walk-forward validation.

Walk-forward: expanding window, 1-year test folds.
Purge: removes rows within `embargo_weeks` of the train/test boundary.
"""
import logging
import os
import pickle
from dataclasses import dataclass
from datetime import date

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import precision_score, recall_score, f1_score
from sklearn.preprocessing import StandardScaler
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.stock import Stock
from app.models.feature import FeatureWeekly, LabelWeekly
from app.services.backtester import Backtester
from app.models.price import PriceDaily

logger = logging.getLogger(__name__)

MODELS_DIR = "/app/models_store"
os.makedirs(MODELS_DIR, exist_ok=True)


@dataclass
class WalkForwardFold:
    fold: int
    train_start: date
    train_end: date
    test_start: date
    test_end: date
    metrics: dict
    n_trades: int


class ModelTrainer:
    def __init__(self, session: Session, strategy_config: dict):
        self.session = session
        self.config = strategy_config
        self.model_type = strategy_config.get("model_type", "lightgbm")
        self.features = strategy_config.get("features", [])
        self.target = strategy_config.get("target", "target_2pct_1w")
        self.threshold = strategy_config.get("threshold", 0.5)
        self.embargo_weeks = strategy_config.get("embargo_weeks", 4)
        self.top_n = strategy_config.get("top_n", 5)

    def load_dataset(self, tickers: list[str]) -> pd.DataFrame:
        """Pivot long-format features into wide format and join labels."""
        stocks = {
            s.ticker: s.id
            for s in self.session.execute(select(Stock).where(Stock.ticker.in_(tickers))).scalars().all()
        }
        stock_ids = list(stocks.values())
        id_to_ticker = {v: k for k, v in stocks.items()}

        # Features
        feat_rows = self.session.execute(
            select(FeatureWeekly).where(FeatureWeekly.stock_id.in_(stock_ids))
        ).scalars().all()

        if not feat_rows:
            return pd.DataFrame()

        feat_df = pd.DataFrame([{
            "stock_id": r.stock_id,
            "week_ending": r.week_ending,
            "feature_name": r.feature_name,
            "value": r.value,
        } for r in feat_rows])
        feat_wide = feat_df.pivot_table(
            index=["stock_id", "week_ending"],
            columns="feature_name",
            values="value",
        ).reset_index()

        # Labels
        label_rows = self.session.execute(
            select(LabelWeekly).where(
                LabelWeekly.stock_id.in_(stock_ids),
                LabelWeekly.target_name == self.target,
            )
        ).scalars().all()
        label_df = pd.DataFrame([{
            "stock_id": r.stock_id,
            "week_ending": r.week_ending,
            "label": r.value,
        } for r in label_rows])

        merged = feat_wide.merge(label_df, on=["stock_id", "week_ending"], how="inner")
        merged["ticker"] = merged["stock_id"].map(id_to_ticker)
        merged["week_ending"] = pd.to_datetime(merged["week_ending"])
        return merged.dropna(subset=["label"])

    def walk_forward(self, tickers: list[str], min_train_years: int = 5) -> list[WalkForwardFold]:
        df = self.load_dataset(tickers)
        if df.empty:
            logger.warning("Empty dataset, skipping walk-forward")
            return []

        df = df.sort_values("week_ending")
        all_weeks = sorted(df["week_ending"].unique())

        if len(all_weeks) < 52 * (min_train_years + 1):
            logger.warning("Not enough data for walk-forward")
            return []

        folds: list[WalkForwardFold] = []
        test_window = 52  # 1 year of test weeks

        # Build fold boundaries
        train_end_idx = 52 * min_train_years
        fold_num = 0
        while train_end_idx + test_window <= len(all_weeks):
            train_end = all_weeks[train_end_idx - 1]
            test_start = all_weeks[train_end_idx + self.embargo_weeks]
            test_end = all_weeks[min(train_end_idx + test_window - 1, len(all_weeks) - 1)]

            train = df[df["week_ending"] <= train_end]
            test = df[(df["week_ending"] >= test_start) & (df["week_ending"] <= test_end)]

            if len(train) < 100 or len(test) < 10:
                train_end_idx += test_window
                continue

            model, scaler = self._train(train)
            metrics = self._evaluate(model, scaler, test, tickers)

            folds.append(WalkForwardFold(
                fold=fold_num,
                train_start=all_weeks[0].date(),
                train_end=train_end.date(),
                test_start=test_start.date(),
                test_end=test_end.date(),
                metrics=metrics,
                n_trades=metrics.get("n_trades", 0),
            ))

            fold_num += 1
            train_end_idx += test_window

        return folds

    def _train(self, train_df: pd.DataFrame):
        feature_cols = [c for c in self.features if c in train_df.columns]
        if not feature_cols:
            feature_cols = [c for c in train_df.columns if c not in ["stock_id", "week_ending", "label", "ticker"]]

        X = train_df[feature_cols].fillna(0).values
        y = train_df["label"].values

        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)

        if self.model_type == "lightgbm":
            pos_weight = (y == 0).sum() / max((y == 1).sum(), 1)
            model = lgb.LGBMClassifier(
                n_estimators=200,
                max_depth=4,
                num_leaves=15,
                learning_rate=0.05,
                subsample=0.8,
                colsample_bytree=0.8,
                scale_pos_weight=pos_weight,
                random_state=42,
                verbose=-1,
            )
            model.fit(X_scaled, y)
        else:  # logistic regression baseline
            model = LogisticRegression(C=0.1, max_iter=1000, random_state=42)
            model.fit(X_scaled, y)

        return model, scaler

    def _evaluate(self, model, scaler, test_df: pd.DataFrame, tickers: list[str]) -> dict:
        feature_cols = [c for c in self.features if c in test_df.columns]
        if not feature_cols:
            feature_cols = [c for c in test_df.columns if c not in ["stock_id", "week_ending", "label", "ticker"]]

        X = test_df[feature_cols].fillna(0).values
        y = test_df["label"].values
        X_scaled = scaler.transform(X)

        probs = model.predict_proba(X_scaled)[:, 1]
        preds = (probs >= self.threshold).astype(int)

        precision = precision_score(y, preds, zero_division=0)
        recall = recall_score(y, preds, zero_division=0)
        f1 = f1_score(y, preds, zero_division=0)

        # Build predictions df for backtester
        pred_df = test_df[["week_ending", "ticker", "stock_id"]].copy()
        pred_df["prob"] = probs

        # Load prices for backtester
        price_df = self._load_prices_for_tickers(tickers)

        bt = Backtester(pred_df, price_df, threshold=self.threshold, top_n=self.top_n)
        bt_result = bt.run()

        metrics = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            **bt_result.to_dict(),
        }
        return metrics

    def _load_prices_for_tickers(self, tickers: list[str]) -> pd.DataFrame:
        stocks = self.session.execute(
            select(Stock).where(Stock.ticker.in_(tickers))
        ).scalars().all()
        stock_ids = [s.id for s in stocks]
        id_to_ticker = {s.id: s.ticker for s in stocks}

        rows = self.session.execute(
            select(PriceDaily).where(PriceDaily.stock_id.in_(stock_ids))
        ).scalars().all()

        return pd.DataFrame([{
            "date": r.date,
            "ticker": id_to_ticker[r.stock_id],
            "open": r.open,
            "close": r.close,
        } for r in rows])

    def train_final_model(self, tickers: list[str], train_end: date):
        """Train a single model on all data up to train_end for production use."""
        df = self.load_dataset(tickers)
        train = df[df["week_ending"] <= pd.Timestamp(train_end)]
        model, scaler = self._train(train)
        return model, scaler

    def save_model(self, model, scaler, strategy_id: int, fold: int = -1) -> str:
        path = os.path.join(MODELS_DIR, f"strategy_{strategy_id}_fold_{fold}.pkl")
        with open(path, "wb") as f:
            pickle.dump({"model": model, "scaler": scaler, "config": self.config}, f)
        return path

    @staticmethod
    def load_model(path: str):
        with open(path, "rb") as f:
            return pickle.load(f)
