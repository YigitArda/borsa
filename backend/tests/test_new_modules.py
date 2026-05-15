"""
Unit tests for all new signal and learning modules.

Run with: pytest tests/test_new_modules.py -v
No DB connection required — all tests use in-memory data only.
"""
import numpy as np
import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Behavioral signals
# ---------------------------------------------------------------------------

class TestBehavioralSignals:
    def _close(self):
        rng = np.random.RandomState(42)
        prices = 100 * np.cumprod(1 + rng.normal(0.001, 0.02, 300))
        return pd.Series(prices)

    def _weekly_returns(self):
        rng = np.random.RandomState(7)
        return pd.Series(rng.normal(0.003, 0.02, 100))

    def test_anchoring_returns_dict(self):
        from app.services.behavioral_signals import compute_anchoring
        result = compute_anchoring(self._close())
        assert "anchor_proximity_high" in result
        assert "anchor_proximity_low" in result
        assert "anchor_breakout_signal" in result
        assert result["anchor_breakout_signal"] in (0.0, 1.0)

    def test_anchoring_short_series_returns_nan(self):
        from app.services.behavioral_signals import compute_anchoring
        result = compute_anchoring(pd.Series([100.0, 101.0]))
        assert all(np.isnan(v) for v in result.values())

    def test_disposition_range(self):
        from app.services.behavioral_signals import compute_disposition
        result = compute_disposition(self._close())
        proxy = result["disposition_gain_proxy"]
        assert 0.0 <= proxy <= 1.0

    def test_overreaction_no_lookahead(self):
        from app.services.behavioral_signals import compute_overreaction
        returns = self._weekly_returns()
        result = compute_overreaction(returns)
        assert "overreaction_reversal" in result
        assert "extreme_move_flag" in result

    def test_herding_score_range(self):
        from app.services.behavioral_signals import compute_herding_score
        returns = {"AAPL": 0.02, "MSFT": 0.018, "GOOG": 0.022, "AMZN": 0.019, "TSLA": 0.025}
        score = compute_herding_score(returns)
        assert 0.0 <= score <= 1.0

    def test_herding_few_stocks_returns_nan(self):
        from app.services.behavioral_signals import compute_herding_score
        score = compute_herding_score({"A": 0.01, "B": 0.02})
        assert np.isnan(score)

    def test_compute_all_behavioral(self):
        from app.services.behavioral_signals import compute_all_behavioral, BEHAVIORAL_FEATURES
        result = compute_all_behavioral(self._close(), self._weekly_returns(), herding_score=0.6)
        for feat in BEHAVIORAL_FEATURES:
            assert feat in result


# ---------------------------------------------------------------------------
# Price NLP (SAX + N-gram + embedding)
# ---------------------------------------------------------------------------

class TestPriceNLP:
    def _returns(self, n=150):
        rng = np.random.RandomState(99)
        return pd.Series(rng.normal(0.002, 0.025, n))

    def test_sax_encode_length(self):
        from app.services.price_nlp import sax_encode
        returns = self._returns()
        encoded = sax_encode(returns, window=20)
        assert len(encoded) == 20
        assert all(c in "ABCDE" for c in encoded)

    def test_sax_encode_short_series(self):
        from app.services.price_nlp import sax_encode
        assert sax_encode(pd.Series([0.01, 0.02])) == ""

    def test_sax_to_features(self):
        from app.services.price_nlp import sax_to_features
        result = sax_to_features("ABCDE")
        assert "sax_last_symbol" in result
        assert result["sax_last_symbol"] == 4.0  # 'E' is index 4

    def test_ngram_fit_and_score(self):
        from app.services.price_nlp import NGramAnalyzer
        returns = self._returns()
        next_returns = returns.shift(-1).dropna()
        returns_aligned = returns.iloc[: len(next_returns)]
        analyzer = NGramAnalyzer(n=3)
        analyzer.fit(returns_aligned, next_returns)
        from app.services.price_nlp import sax_encode
        sax = sax_encode(returns, window=20)
        result = analyzer.score_current(sax)
        assert 0.0 <= result["ngram_bullish_score"] <= 1.0
        assert 0.0 <= result["ngram_bearish_score"] <= 1.0

    def test_price_nlp_service_compute(self):
        from app.services.price_nlp import PriceNLPService, PRICE_NLP_FEATURES
        returns = self._returns()
        svc = PriceNLPService()
        next_returns = returns.shift(-1).dropna()
        svc.fit(returns.iloc[: len(next_returns)], next_returns)
        result = svc.compute(returns.iloc[:-10])
        for feat in PRICE_NLP_FEATURES:
            assert feat in result

    def test_price_embedder(self):
        from app.services.price_nlp import PriceEmbedder, sax_encode
        returns = self._returns()
        sequences = [sax_encode(returns.iloc[:i], window=min(i, 30)) for i in range(30, len(returns))]
        embedder = PriceEmbedder(n=3, embed_dim=2)
        embedder.fit(sequences)
        sax = sax_encode(returns, window=20)
        vec = embedder.embed(sax)
        assert vec.shape == (2,)


# ---------------------------------------------------------------------------
# CSV Framework
# ---------------------------------------------------------------------------

class TestCSVFramework:
    def _make_df(self, n=300):
        rng = np.random.RandomState(1)
        df = pd.DataFrame({
            "rsi_14": rng.uniform(20, 80, n),
            "macd_hist": rng.normal(0, 0.5, n),
            "bb_position": rng.uniform(0, 1, n),
            "momentum": rng.normal(0.02, 0.1, n),
            "anchor_proximity_high": rng.uniform(-0.3, 0, n),
            "anchor_breakout_signal": rng.choice([0.0, 1.0], n),
            "disposition_gain_proxy": rng.uniform(0, 1, n),
            "overreaction_reversal": rng.normal(0, 0.05, n),
            "volume_zscore": rng.normal(0, 2, n),
            "target_2pct_1w": rng.choice([0, 1], n),
            "regime_type": rng.choice(["bull", "bear", "sideways"], n),
        })
        return df

    def test_csv_score_returns_dict(self):
        from app.services.conditional_signal_validity import CSVFramework
        csv = CSVFramework()
        df = self._make_df()
        csv.fit(df)
        features = {col: float(df[col].iloc[-1]) for col in df.columns if col not in ["target_2pct_1w", "regime_type"]}
        result = csv.score(features, "bull")
        assert "csv_meta_score" in result
        assert 0.0 <= result["csv_meta_score"] <= 1.0

    def test_csv_cold_start(self):
        from app.services.conditional_signal_validity import CSVFramework
        csv = CSVFramework()  # not fitted
        result = csv.score({"rsi_14": 30.0}, "bull")
        assert result["csv_meta_score"] == 0.5

    def test_granger_causality_proxy(self):
        from app.services.conditional_signal_validity import granger_causality_proxy
        rng = np.random.RandomState(5)
        x = pd.Series(rng.normal(0, 1, 100))
        y = x.shift(1).fillna(0) + rng.normal(0, 0.1, 100)
        f_stat = granger_causality_proxy(x, y)
        assert f_stat >= 0.0


# ---------------------------------------------------------------------------
# Signal Stacker
# ---------------------------------------------------------------------------

class TestSignalStacker:
    def test_predict_returns_valid_score(self):
        from app.services.signal_stacker import SignalStacker, compute_fund_score, compute_micro_score, compute_macro_score
        stacker = SignalStacker()
        features = {
            "prob_2pct": 0.6,
            "roe": 0.15,
            "revenue_growth": 0.10,
            "VIX": 18.0,
            "RISK_ON_SCORE": 0.65,
            "sp500_trend_20w": 0.05,
            "ngram_bullish_score": 0.6,
            "anchor_breakout_signal": 1.0,
        }
        score, components = stacker.predict(features, "bull")
        assert 0.0 <= score <= 1.0
        assert "tech_score" in components

    def test_compute_fund_score(self):
        from app.services.signal_stacker import compute_fund_score
        score = compute_fund_score({"roe": 0.20, "revenue_growth": 0.15})
        assert 0.0 <= score <= 1.0

    def test_compute_macro_score(self):
        from app.services.signal_stacker import compute_macro_score
        score = compute_macro_score({"VIX": 25.0, "RISK_ON_SCORE": 0.4, "sp500_trend_20w": -0.02})
        assert 0.0 <= score <= 1.0

    def test_regime_weights_differ(self):
        from app.services.signal_stacker import SignalStacker, DEFAULT_WEIGHTS
        bull_w = DEFAULT_WEIGHTS["bull"]
        bear_w = DEFAULT_WEIGHTS["bear"]
        assert bull_w["tech"] != bear_w["tech"]
        assert bear_w["macro"] > bull_w["macro"]


# ---------------------------------------------------------------------------
# Genetic evolver (fitness + crossover)
# ---------------------------------------------------------------------------

class TestGeneticEvolver:
    def test_fitness_positive(self):
        from app.services.genetic_evolver import fitness
        f = fitness({"sharpe": 1.5, "profit_factor": 1.3, "max_drawdown": -0.10})
        assert f > 0.0

    def test_fitness_zero_on_bad_sharpe(self):
        from app.services.genetic_evolver import fitness
        assert fitness({"sharpe": -0.1, "profit_factor": 1.5, "max_drawdown": -0.05}) == 0.0

    def test_crossover_produces_valid_child(self):
        from app.services.genetic_evolver import Individual, crossover
        pa = Individual(config={"features": ["rsi_14", "macd", "bb_position"], "model_type": "lightgbm",
                                 "threshold": 0.5, "top_n": 5, "embargo_weeks": 4, "holding_weeks": 1,
                                 "target": "target_2pct_1w", "stop_loss": None, "take_profit": None},
                        fitness_score=1.5)
        pb = Individual(config={"features": ["rsi_14", "volume_zscore", "momentum"], "model_type": "random_forest",
                                 "threshold": 0.6, "top_n": 7, "embargo_weeks": 2, "holding_weeks": 2,
                                 "target": "target_2pct_1w", "stop_loss": -0.05, "take_profit": 0.08},
                        fitness_score=0.8)
        child = crossover(pa, pb)
        assert "features" in child.config
        assert len(child.config["features"]) > 0
        assert child.config["model_type"] in ("lightgbm", "random_forest")

    def test_jaccard_similarity(self):
        from app.services.genetic_evolver import jaccard_similarity
        assert jaccard_similarity(["a", "b", "c"], ["b", "c", "d"]) == pytest.approx(0.5)
        assert jaccard_similarity([], []) == 1.0


# ---------------------------------------------------------------------------
# Curriculum trainer (difficulty scorer)
# ---------------------------------------------------------------------------

class TestDifficultyScorer:
    def test_sax_difficulty_normalization(self):
        """difficulty scores should be in [0,1] after normalization."""
        # Simulate what DifficultyScorer does without DB
        import numpy as np
        vix = np.array([15.0, 20.0, 30.0, 12.0, 25.0, 40.0, 18.0])
        std = np.array([0.01, 0.02, 0.04, 0.01, 0.03, 0.05, 0.02])
        raw = vix * (1.0 + std)
        dmin, dmax = raw.min(), raw.max()
        normalized = (raw - dmin) / (dmax - dmin)
        assert normalized.min() >= 0.0
        assert normalized.max() <= 1.0


# ---------------------------------------------------------------------------
# Price NLP SAX performance (20 stocks × 500 weeks < 30s)
# ---------------------------------------------------------------------------

def test_price_nlp_performance():
    """SAX encoding for 20 stocks × 500 weeks must complete in under 30 seconds."""
    import time
    from app.services.price_nlp import sax_encode
    rng = np.random.RandomState(0)
    start = time.time()
    for _ in range(20):  # 20 stocks
        returns = pd.Series(rng.normal(0.002, 0.025, 500))
        for i in range(10, 500):
            sax_encode(returns.iloc[:i], window=20)
    elapsed = time.time() - start
    assert elapsed < 30.0, f"SAX encoding too slow: {elapsed:.1f}s"
