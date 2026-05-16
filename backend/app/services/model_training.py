"""
LightGBM model training with walk-forward validation.

Walk-forward: expanding window, 1-year test folds.
Purge: removes rows within `embargo_weeks` of the train/test boundary.
"""
import logging
import os
import pickle
from itertools import combinations
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.metrics import precision_score, recall_score, f1_score
from sklearn.preprocessing import StandardScaler
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.config import settings

try:
    import xgboost as xgb
    HAS_XGBOOST = True
except ImportError:
    HAS_XGBOOST = False

try:
    from catboost import CatBoostClassifier
    HAS_CATBOOST = True
except ImportError:
    HAS_CATBOOST = False

from app.models.stock import Stock
from app.models.feature import FeatureWeekly, LabelWeekly
from app.services.backtester import Backtester
from app.models.price import PriceDaily
from app.services.price_adjustments import adjusted_ohlc

logger = logging.getLogger(__name__)

try:
    import lightgbm as lgb
    HAS_LIGHTGBM = True
except ImportError:
    lgb = None
    HAS_LIGHTGBM = False

MODELS_DIR = os.getenv("MODELS_DIR", settings.models_dir)
try:
    os.makedirs(MODELS_DIR, exist_ok=True)
except PermissionError:
    MODELS_DIR = os.path.abspath("models_store")
    os.makedirs(MODELS_DIR, exist_ok=True)

NON_FEATURE_COLUMNS = {
    "stock_id",
    "week_ending",
    "label",
    "ticker",
    "sector",
    # all possible target label names — guard against accidental inclusion
    "target_2pct_1w",
    "target_3pct_1w",
    "risk_target_1w",
    "risk_target_3pct_1w",
    "next_week_return",
    "next_2week_return",
    "next_4week_return",
}


@dataclass
class WalkForwardFold:
    fold: int
    train_start: date
    train_end: date
    test_start: date
    test_end: date
    metrics: dict
    n_trades: int
    trade_returns: list[float] = None      # individual trade returns for statistical tests
    trade_details: list[dict] = None       # ticker + entry_date + return_pct
    equity_curve: list[dict] = None        # [{date, equity}] for charting


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

    def walk_forward(
        self,
        tickers: list[str],
        min_train_years: int = 5,
        apply_liquidity_filter: bool = True,
        holdout_cutoff=None,
    ) -> list[WalkForwardFold]:
        if apply_liquidity_filter:
            from app.services.data_ingestion import DataIngestionService
            svc = DataIngestionService(self.session)
            tickers = svc.liquidity_filter(tickers)
            if not tickers:
                logger.warning("All tickers filtered out by liquidity filter")
                return []

        df = self.load_dataset(tickers)
        if df.empty:
            logger.warning("Empty dataset, skipping walk-forward")
            return []

        # HOLDOUT ENFORCEMENT — son N ayı training/validation'dan kapat
        if holdout_cutoff is not None:
            original_len = len(df)
            df = df[df["week_ending"] < pd.Timestamp(holdout_cutoff)]
            logger.info(
                "Holdout enforcement: %d rows removed (cutoff: %s)",
                original_len - len(df),
                holdout_cutoff,
            )
            if df.empty:
                logger.warning("No data before holdout cutoff — training aborted")
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
            # Pass prior folds so Kelly is estimated from history, not future
            metrics = self._evaluate(model, scaler, test, tickers, prior_folds=folds)

            folds.append(WalkForwardFold(
                fold=fold_num,
                train_start=all_weeks[0].date(),
                train_end=train_end.date(),
                test_start=test_start.date(),
                test_end=test_end.date(),
                metrics={k: v for k, v in metrics.items() if not k.startswith("_")},
                n_trades=metrics.get("n_trades", 0),
                trade_returns=metrics.get("_trade_returns", []),
                trade_details=metrics.get("_trade_details", []),
                equity_curve=metrics.get("_equity_curve", []),
            ))

            fold_num += 1
            train_end_idx += test_window

        return folds

    def combinatorial_purged_cv(
        self,
        tickers: list[str],
        n_groups: int = 6,
        n_test_groups: int = 2,
        min_train_rows: int = 100,
        apply_liquidity_filter: bool = True,
    ) -> list[WalkForwardFold]:
        """Combinatorial purged cross-validation for robustness checks.

        This is a research validation tool, not a production deployment split.
        Test groups are calendar-ordered week blocks; train rows inside the
        configured embargo distance from any test week are purged.
        """
        if n_groups < 3:
            raise ValueError("n_groups must be >= 3")
        if n_test_groups < 1 or n_test_groups >= n_groups:
            raise ValueError("n_test_groups must be in [1, n_groups)")

        if apply_liquidity_filter:
            from app.services.data_ingestion import DataIngestionService
            tickers = DataIngestionService(self.session).liquidity_filter(tickers)
            if not tickers:
                return []

        df = self.load_dataset(tickers)
        if df.empty:
            return []

        df = df.sort_values("week_ending")
        all_weeks = list(pd.to_datetime(sorted(df["week_ending"].unique())))
        if len(all_weeks) < n_groups * 4:
            return []

        week_groups = np.array_split(all_weeks, n_groups)
        folds: list[WalkForwardFold] = []
        fold_num = 0
        for test_group_ids in combinations(range(n_groups), n_test_groups):
            test_weeks = set()
            for group_id in test_group_ids:
                test_weeks.update(week_groups[group_id])

            test_mask = df["week_ending"].isin(test_weeks)
            purge_weeks = set(test_weeks)
            for week in test_weeks:
                for offset in range(1, self.embargo_weeks + 1):
                    purge_weeks.add(week - pd.Timedelta(weeks=offset))
                    purge_weeks.add(week + pd.Timedelta(weeks=offset))

            train = df[~df["week_ending"].isin(purge_weeks)]
            test = df[test_mask]
            if len(train) < min_train_rows or len(test) < 10:
                continue

            model, scaler = self._train(train)
            metrics = self._evaluate(model, scaler, test, tickers)
            folds.append(WalkForwardFold(
                fold=fold_num,
                train_start=train["week_ending"].min().date(),
                train_end=train["week_ending"].max().date(),
                test_start=test["week_ending"].min().date(),
                test_end=test["week_ending"].max().date(),
                metrics={k: v for k, v in metrics.items() if not k.startswith("_")},
                n_trades=metrics.get("n_trades", 0),
                trade_returns=metrics.get("_trade_returns", []),
                trade_details=metrics.get("_trade_details", []),
                equity_curve=metrics.get("_equity_curve", []),
            ))
            fold_num += 1

        return folds

    def _train(self, train_df: pd.DataFrame):
        feature_cols = [c for c in self.features if c in train_df.columns]
        if not feature_cols:
            feature_cols = [c for c in train_df.columns if c not in NON_FEATURE_COLUMNS]

        X = train_df[feature_cols].fillna(0).values
        y = train_df["label"].values

        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)

        pos_weight = (y == 0).sum() / max((y == 1).sum(), 1)

        if self.model_type == "lightgbm" and HAS_LIGHTGBM:
            model = lgb.LGBMClassifier(
                n_estimators=200, max_depth=4, num_leaves=15,
                learning_rate=0.05, subsample=0.8, colsample_bytree=0.8,
                scale_pos_weight=pos_weight, random_state=42, verbose=-1,
            )
            model.fit(X_scaled, y)
        elif self.model_type == "lightgbm" and not HAS_LIGHTGBM:
            logger.warning("LightGBM is not installed; falling back to logistic_regression")
            model = LogisticRegression(C=0.1, max_iter=1000, random_state=42)
            model.fit(X_scaled, y)
        elif self.model_type == "random_forest":
            model = RandomForestClassifier(
                n_estimators=200, max_depth=6, min_samples_leaf=10,
                class_weight="balanced", random_state=42, n_jobs=-1,
            )
            model.fit(X_scaled, y)
        elif self.model_type == "gradient_boosting":
            model = GradientBoostingClassifier(
                n_estimators=150, max_depth=3, learning_rate=0.05,
                subsample=0.8, random_state=42,
            )
            model.fit(X_scaled, y)
        elif self.model_type == "xgboost" and HAS_XGBOOST:
            model = xgb.XGBClassifier(
                n_estimators=200, max_depth=4, learning_rate=0.05,
                subsample=0.8, colsample_bytree=0.8,
                scale_pos_weight=pos_weight, random_state=42,
                eval_metric="logloss", verbosity=0,
            )
            model.fit(X_scaled, y)
        elif self.model_type == "catboost" and HAS_CATBOOST:
            model = CatBoostClassifier(
                iterations=200, depth=4, learning_rate=0.05,
                class_weights=[1, pos_weight], random_seed=42, verbose=0,
            )
            model.fit(X_scaled, y)
        elif self.model_type == "neural_network":
            from sklearn.neural_network import MLPClassifier
            model = MLPClassifier(
                hidden_layer_sizes=(64, 32),
                activation="relu",
                max_iter=300,
                random_state=42,
                early_stopping=True,
                validation_fraction=0.1,
                learning_rate_init=0.001,
            )
            model.fit(X_scaled, y)
        else:  # logistic regression baseline
            model = LogisticRegression(C=0.1, max_iter=1000, random_state=42)
            model.fit(X_scaled, y)

        return model, scaler

    def _evaluate(
        self,
        model,
        scaler,
        test_df: pd.DataFrame,
        tickers: list[str],
        prior_folds: list | None = None,
        kelly_fraction: float = 0.0,
    ) -> dict:
        """
        Evaluate model on test_df.

        Args:
            prior_folds: Walk-forward folds preceding this one; used to compute
                         Kelly fraction from historical trade data (no lookahead).
            kelly_fraction: Pre-computed Kelly to use; overrides prior_folds if > 0.
        """
        feature_cols = [c for c in self.features if c in test_df.columns]
        if not feature_cols:
            feature_cols = [c for c in test_df.columns if c not in NON_FEATURE_COLUMNS]

        X = test_df[feature_cols].fillna(0).values
        y = test_df["label"].values
        X_scaled = scaler.transform(X)

        probs = model.predict_proba(X_scaled)[:, 1]
        preds = (probs >= self.threshold).astype(int)

        precision = precision_score(y, preds, zero_division=0)
        recall = recall_score(y, preds, zero_division=0)
        f1 = f1_score(y, preds, zero_division=0)

        # --- Kelly from prior folds (no lookahead: only folds before this one) ---
        if kelly_fraction <= 0 and prior_folds:
            from app.services.position_sizing import kelly_from_folds
            kelly_est = kelly_from_folds(prior_folds)
            kelly_fraction = kelly_est.fractional_kelly
            logger.debug(
                "Kelly from %d prior folds: fraction=%.4f win_rate=%.2f",
                len(prior_folds), kelly_fraction, kelly_est.win_rate,
            )

        # --- Regime filter from DB ---
        from app.services.regime_filter import RegimeFilter
        test_weeks = sorted(test_df["week_ending"].dt.date.unique() if hasattr(test_df["week_ending"], "dt") else test_df["week_ending"].unique())
        regime_filter = None
        if test_weeks:
            rf = RegimeFilter(self.session)
            try:
                start_date = test_weeks[0] if isinstance(test_weeks[0], __import__("datetime").date) else test_weeks[0].date()
                end_date = test_weeks[-1] if isinstance(test_weeks[-1], __import__("datetime").date) else test_weeks[-1].date()
                rf.load(start_date, end_date)
                regime_filter = rf
            except Exception as exc:
                logger.warning(
                    "Regime filter yüklenemedi: %s — position sizing regime-aware çalışmıyor",
                    exc,
                )

        # Build predictions df for backtester
        pred_df = test_df[["week_ending", "ticker", "stock_id"]].copy()
        pred_df["prob"] = probs

        # Load prices for backtester
        price_df = self._load_prices_for_tickers(tickers)

        bt = Backtester(
            pred_df, price_df,
            threshold=self.threshold,
            top_n=self.top_n,
            holding_weeks=self.config.get("holding_weeks", 1),
            stop_loss=self.config.get("stop_loss"),
            take_profit=self.config.get("take_profit"),
            kelly_fraction=kelly_fraction,
            regime_filter=regime_filter,
        )
        bt_result = bt.run()

        trade_returns = [t.return_pct for t in bt_result.trades]
        trade_details = [
            {"ticker": t.ticker, "entry_date": str(t.entry_date), "return_pct": t.return_pct}
            for t in bt_result.trades
        ]
        equity_curve = [
            {"date": str(idx), "equity": float(val)}
            for idx, val in bt_result.equity_curve.items()
        ] if not bt_result.equity_curve.empty else []

        bt_dict = bt_result.to_dict()
        bt_dict["kelly_fraction"] = round(kelly_fraction, 4)
        if regime_filter is None:
            logger.warning(
                "UYARI: Regime filter aktif değil. "
                "Tüm fold'lar regime filtresi olmadan çalışacak."
            )
        if regime_filter is not None:
            regime_series = regime_filter.as_series()
            weeks_skipped = sum(1 for m in regime_series.values() if m == 0.0)
            bt_dict["regime_weeks_skipped"] = weeks_skipped

        metrics = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            **bt_dict,
            "_trade_returns": trade_returns,
            "_trade_details": trade_details,
            "_equity_curve": equity_curve,
        }

        # SHAP değerleri hesapla
        try:
            import shap
            feature_cols = [c for c in self.features if c in test_df.columns]
            X_sample = test_df[feature_cols].fillna(0).values[:100]
            explainer = shap.TreeExplainer(model)
            shap_values = explainer.shap_values(X_sample)
            if isinstance(shap_values, list):
                shap_values = shap_values[1]
            mean_abs = abs(shap_values).mean(axis=0)
            total = mean_abs.sum() or 1
            metrics["shap_importance"] = {
                f: round(float(v / total), 4)
                for f, v in zip(feature_cols, mean_abs)
            }
        except Exception as e:
            logger.warning("SHAP hesaplanamadı: %s", e)

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
            **adjusted_ohlc(r.open, r.high, r.low, r.close, r.adj_close),
        } for r in rows])

    def get_feature_importance(self, model, feature_cols: list[str]) -> dict[str, float]:
        """Extract feature importances (tree-based native or SHAP fallback)."""
        try:
            if hasattr(model, "feature_importances_"):
                imps = model.feature_importances_
                total = sum(imps) or 1
                return {f: float(v / total) for f, v in zip(feature_cols, imps)}
            elif hasattr(model, "coef_"):
                imps = abs(model.coef_[0])
                total = sum(imps) or 1
                return {f: float(v / total) for f, v in zip(feature_cols, imps)}
        except Exception as e:
            logger.warning("Feature importance extraction failed: %s", e)
        return {}

    def get_shap_values(self, model, X: np.ndarray, feature_cols: list[str]) -> dict[str, float]:
        """Compute mean absolute SHAP values per feature (requires shap library)."""
        try:
            import shap
            if hasattr(model, "predict_proba"):
                explainer = shap.TreeExplainer(model) if hasattr(model, "feature_importances_") else shap.Explainer(model)
                shap_values = explainer.shap_values(X)
                if isinstance(shap_values, list):
                    shap_values = shap_values[1]  # positive class
                mean_abs = np.abs(shap_values).mean(axis=0)
                total = mean_abs.sum() or 1
                return {f: float(v / total) for f, v in zip(feature_cols, mean_abs)}
        except Exception as e:
            logger.debug(f"SHAP computation failed: {e}")
        return {}

    def train_per_stock(self, tickers: list[str], min_rows: int = 100) -> dict[str, dict]:
        """Train a separate model for each stock with enough data."""
        results = {}
        df = self.load_dataset(tickers)
        if df.empty:
            return results

        for ticker in tickers:
            stock_df = df[df["ticker"] == ticker].sort_values("week_ending")
            if len(stock_df) < min_rows:
                logger.info(f"Not enough data for per-stock model: {ticker} ({len(stock_df)} rows)")
                continue

            split = int(len(stock_df) * 0.8)
            train = stock_df.iloc[:split]
            test = stock_df.iloc[split:]

            try:
                model, scaler = self._train(train)
                metrics = self._evaluate(model, scaler, test, [ticker])
                feature_cols = [c for c in self.features if c in train.columns]
                if not feature_cols:
                    feature_cols = [c for c in train.columns if c not in NON_FEATURE_COLUMNS]
                importance = self.get_feature_importance(model, feature_cols)
                results[ticker] = {
                    "metrics": metrics,
                    "top_features": sorted(importance.items(), key=lambda x: -x[1])[:5],
                }
                logger.info(f"Per-stock model {ticker}: sharpe={metrics.get('sharpe')}")
            except Exception as e:
                logger.error(f"Per-stock model failed {ticker}: {e}")

        return results

    def train_per_sector(self, tickers: list[str], min_rows: int = 200) -> dict[str, dict]:
        """Train one model per sector grouping (tech, financials, energy, etc.)."""
        results = {}
        df = self.load_dataset(tickers)
        if df.empty:
            return results

        stocks = self.session.execute(
            select(Stock).where(Stock.ticker.in_(tickers))
        ).scalars().all()
        ticker_to_sector = {s.ticker: (s.sector or "Unknown") for s in stocks}
        df["sector"] = df["ticker"].map(ticker_to_sector).fillna("Unknown")

        for sector, sector_df in df.groupby("sector"):
            sector_df = sector_df.sort_values("week_ending")
            if len(sector_df) < min_rows:
                logger.info(f"Not enough data for sector model: {sector} ({len(sector_df)} rows)")
                continue

            split = int(len(sector_df) * 0.8)
            train = sector_df.iloc[:split]
            test = sector_df.iloc[split:]

            try:
                model, scaler = self._train(train)
                sector_tickers = list(sector_df["ticker"].unique())
                metrics = self._evaluate(model, scaler, test, sector_tickers)
                feature_cols = [c for c in self.features if c in train.columns]
                if not feature_cols:
                    feature_cols = [c for c in train.columns if c not in NON_FEATURE_COLUMNS]
                importance = self.get_feature_importance(model, feature_cols)
                results[sector] = {
                    "n_stocks": len(sector_tickers),
                    "metrics": metrics,
                    "top_features": sorted(importance.items(), key=lambda x: -x[1])[:5],
                }
                logger.info(f"Sector model {sector}: sharpe={metrics.get('sharpe')}")
            except Exception as e:
                logger.error(f"Sector model failed {sector}: {e}")

        return results

    def predict_all(self, df: pd.DataFrame, min_train_weeks: int = 104) -> pd.DataFrame:
        """Generate out-of-sample predictions via expanding-window walk-forward.

        Trains on all weeks before each target week and predicts that week.
        Returns a DataFrame with [week_ending, ticker, stock_id, prob] columns
        suitable for passing directly to Backtester.
        """
        if df.empty:
            return pd.DataFrame(columns=["week_ending", "ticker", "stock_id", "prob"])

        df = df.sort_values("week_ending")
        all_weeks = sorted(df["week_ending"].unique())

        if len(all_weeks) < min_train_weeks + 1:
            logger.warning("predict_all: not enough weeks (%d < %d)", len(all_weeks), min_train_weeks + 1)
            return pd.DataFrame(columns=["week_ending", "ticker", "stock_id", "prob"])

        feature_cols: list[str] | None = None
        rows = []

        for week in all_weeks[min_train_weeks:]:
            train = df[df["week_ending"] < week].dropna(subset=["label"])
            test = df[df["week_ending"] == week]
            if len(train) < 100 or test.empty:
                continue
            if feature_cols is None:
                feature_cols = [c for c in self.features if c in train.columns]
                if not feature_cols:
                    feature_cols = [c for c in train.columns if c not in NON_FEATURE_COLUMNS]
            try:
                model, scaler = self._train(train)
                X = test[feature_cols].fillna(0).values
                probs = model.predict_proba(scaler.transform(X))[:, 1]
                for j, (_, row) in enumerate(test.iterrows()):
                    rows.append({
                        "week_ending": week,
                        "ticker": row["ticker"],
                        "stock_id": int(row["stock_id"]),
                        "prob": float(probs[j]),
                    })
            except Exception as exc:
                logger.warning("predict_all: week %s skipped: %s", week, exc)

        return pd.DataFrame(rows)

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


class HoldoutValidator:
    """Son N ayı hiç dokunulmadan tutar — sadece final OOS doğrulama için."""

    def __init__(self, session, holdout_months: int = 18):
        self.session = session
        self.holdout_months = holdout_months

    def get_holdout_data(self, tickers: list[str], strategy_config: dict) -> pd.DataFrame:
        from dateutil.relativedelta import relativedelta
        cutoff = date.today() - relativedelta(months=self.holdout_months)
        trainer = ModelTrainer(self.session, strategy_config)
        df = trainer.load_dataset(tickers)
        holdout_df = df[df["week_ending"] >= pd.Timestamp(cutoff)]
        logger.info(
            "Holdout data: %d rows from %s to %s",
            len(holdout_df), cutoff, date.today(),
        )
        return holdout_df

    def evaluate_on_holdout(self, strategy_id: int, tickers: list[str]) -> dict:
        """
        Tüm research tamamlandıktan sonra holdout döneminde bir kez çağrıl.
        Sadece promotion kararından ÖNCE kullanılmalı.
        """
        from dateutil.relativedelta import relativedelta
        from app.models.strategy import Strategy
        strategy = self.session.get(Strategy, strategy_id)
        if not strategy:
            return {"error": "strategy not found"}

        cutoff = date.today() - relativedelta(months=self.holdout_months)
        trainer = ModelTrainer(self.session, strategy.config)
        full_df = trainer.load_dataset(tickers)

        train_df = full_df[full_df["week_ending"] < pd.Timestamp(cutoff)]
        holdout_df = full_df[full_df["week_ending"] >= pd.Timestamp(cutoff)]

        if len(train_df) < 100:
            return {"error": "insufficient training data"}
        if holdout_df.empty:
            return {"error": "no holdout data available"}

        model, scaler = trainer._train(train_df)
        metrics = trainer._evaluate(model, scaler, holdout_df, tickers)

        return {
            "strategy_id": strategy_id,
            "holdout_start": str(cutoff),
            "holdout_rows": len(holdout_df),
            "holdout_metrics": {k: v for k, v in metrics.items() if not k.startswith("_")},
        }
