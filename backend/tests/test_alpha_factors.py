"""
Unit tests for Alpha Factors: Momentum+LowVol, PEAD, Short Interest, Combiner.

Run with: pytest tests/test_alpha_factors.py -v
No DB connection required — all tests use in-memory data only.
"""
import math
import numpy as np
import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Factor 1A-1D: Momentum + Low-Vol + BAB + QMJ + Ranking
# ---------------------------------------------------------------------------

class TestMomentumLowVol:
    def _returns(self, n=60, seed=42):
        rng = np.random.RandomState(seed)
        return pd.Series(rng.normal(0.003, 0.02, n))

    def test_basic_features_present(self):
        from app.services.factor_momentum_lowvol import compute_momentum_features
        wr = self._returns()
        result = compute_momentum_features(wr)
        for key in ["momentum_12_1", "momentum_6_1", "combined_momentum", "realized_vol_12w", "vol_score"]:
            assert key in result

    def test_momentum_12_1_skips_last_week(self):
        from app.services.factor_momentum_lowvol import compute_momentum_features
        # Returns: first 12 positive, last one large negative
        wr = pd.Series([0.01] * 12 + [-0.10])
        result = compute_momentum_features(wr)
        # momentum_12_1 should reflect only first 12 (skipping last)
        assert result["momentum_12_1"] > 0.0

    def test_vol_score_inverse_of_vol(self):
        from app.services.factor_momentum_lowvol import compute_momentum_features
        low_vol = pd.Series([0.001] * 60)
        high_vol = pd.Series(np.random.RandomState(7).normal(0, 0.05, 60))
        r_low = compute_momentum_features(low_vol)
        r_high = compute_momentum_features(high_vol)
        assert r_low["vol_score"] > r_high["vol_score"]

    def test_short_series_returns_nan(self):
        from app.services.factor_momentum_lowvol import compute_momentum_features
        wr = pd.Series([0.01, 0.02])
        result = compute_momentum_features(wr)
        # Should return nan for most keys
        assert any(np.isnan(v) for v in result.values() if isinstance(v, float))

    def test_beta_52w_correlated(self):
        from app.services.factor_momentum_lowvol import compute_beta_52w
        rng = np.random.RandomState(1)
        market = pd.Series(rng.normal(0.005, 0.02, 60))
        stock = market * 1.5 + rng.normal(0, 0.005, 60)  # beta ≈ 1.5
        beta = compute_beta_52w(stock, market)
        assert abs(beta - 1.5) < 0.3  # allow ±0.3 tolerance

    def test_beta_short_series_nan(self):
        from app.services.factor_momentum_lowvol import compute_beta_52w
        short = pd.Series([0.01, 0.02])
        sp500 = pd.Series([0.01, 0.02])
        assert np.isnan(compute_beta_52w(short, sp500))

    def test_qmj_score_good_company(self):
        from app.services.factor_momentum_lowvol import compute_qmj_score
        good = {"roe": 0.25, "roa": 0.15, "gross_margin": 0.60, "operating_margin": 0.30,
                "revenue_growth": 0.20, "earnings_growth": 0.25,
                "debt_to_equity": 0.2, "current_ratio": 3.0}
        bad = {"roe": -0.05, "roa": -0.02, "gross_margin": 0.15, "operating_margin": 0.02,
               "revenue_growth": -0.10, "earnings_growth": -0.20,
               "debt_to_equity": 5.0, "current_ratio": 0.8}
        good_score = compute_qmj_score(good)
        bad_score = compute_qmj_score(bad)
        assert good_score > bad_score

    def test_qmj_empty_returns_nan(self):
        from app.services.factor_momentum_lowvol import compute_qmj_score
        assert np.isnan(compute_qmj_score({}))

    def test_combined_momentum_weights(self):
        from app.services.factor_momentum_lowvol import compute_momentum_features
        rng = np.random.RandomState(99)
        wr = pd.Series(rng.normal(0.01, 0.01, 52))
        r = compute_momentum_features(wr)
        expected = 0.7 * r["momentum_12_1"] + 0.3 * r["momentum_6_1"]
        assert abs(r["combined_momentum"] - expected) < 1e-6


# ---------------------------------------------------------------------------
# Factor 2A-2E: PEAD
# ---------------------------------------------------------------------------

class TestPEADFactor:
    def test_pead_decay_at_zero(self):
        from app.services.pead_factor import pead_decay
        assert pead_decay(0) == pytest.approx(1.0)

    def test_pead_decay_at_six(self):
        from app.services.pead_factor import pead_decay
        assert pead_decay(6) == pytest.approx(0.0)

    def test_pead_decay_midpoint(self):
        from app.services.pead_factor import pead_decay
        assert pead_decay(3) == pytest.approx(0.5)

    def test_pead_decay_clamps_at_zero(self):
        from app.services.pead_factor import pead_decay
        assert pead_decay(100) == pytest.approx(0.0)

    def test_pead_features_list_complete(self):
        from app.services.pead_factor import PEAD_FEATURES
        required = [
            "sue_score", "weeks_since_earnings", "pead_signal_strength",
            "pead_decay", "earnings_surprise_direction",
            "drift_confirmed", "drift_strength",
        ]
        for feat in required:
            assert feat in PEAD_FEATURES


# ---------------------------------------------------------------------------
# Factor 3A-3D: Short Interest
# ---------------------------------------------------------------------------

class TestShortInterestFactor:
    def test_features_list_complete(self):
        from app.services.short_interest_factor import SHORT_INTEREST_FEATURES
        required = [
            "short_interest_ratio", "short_ratio_change", "short_squeeze_risk",
            "days_to_cover", "dtc_zscore", "dtc_change",
            "squeeze_score", "sector_short_zscore", "relative_to_sector_short",
        ]
        for feat in required:
            assert feat in SHORT_INTEREST_FEATURES

    def test_kelly_size_range(self):
        from app.services.alpha_factor_combiner import kelly_factor_size
        for p in [0.5, 0.6, 0.7]:
            for b in [1.0, 1.5, 2.0]:
                size = kelly_factor_size(p, b)
                assert 0.0 <= size <= 0.25

    def test_kelly_zero_on_bad_edge_ratio(self):
        from app.services.alpha_factor_combiner import kelly_factor_size
        assert kelly_factor_size(0.0, 1.5) == 0.0
        assert kelly_factor_size(0.5, 0.0) == 0.0


# ---------------------------------------------------------------------------
# Factor 4A-4C: Alpha Combiner
# ---------------------------------------------------------------------------

class TestAlphaFactorCombiner:
    def _make_features(self, mlv=1.0, pead_str=2.0, squeeze=2.0, mom12=0.05,
                       weeks_since=2.0, prob=0.65, dtc=4.0):
        return {
            "mom_lowvol_score": mlv,
            "pead_signal_strength": pead_str,
            "squeeze_score": squeeze,
            "momentum_12_1": mom12,
            "weeks_since_earnings": weeks_since,
            "prob_2pct": prob,
            "days_to_cover": dtc,
        }

    def test_output_keys(self):
        from app.services.alpha_factor_combiner import AlphaFactorCombiner, ALPHA_COMBO_FEATURES
        combiner = AlphaFactorCombiner()
        result = combiner.compute(self._make_features())
        for key in ALPHA_COMBO_FEATURES:
            assert key in result

    def test_three_factor_alignment_high_conviction(self):
        from app.services.alpha_factor_combiner import AlphaFactorCombiner
        combiner = AlphaFactorCombiner()
        result = combiner.compute(self._make_features(mlv=2.5, pead_str=4.0, squeeze=3.0, mom12=0.10))
        assert result["alpha_alignment"] == 3
        assert result["conviction_label"] in ("HIGH_CONVICTION", "STRONG")

    def test_zero_factors_low_alpha(self):
        from app.services.alpha_factor_combiner import AlphaFactorCombiner
        combiner = AlphaFactorCombiner()
        result = combiner.compute({
            "mom_lowvol_score": -2.0,
            "pead_signal_strength": 0.0,
            "squeeze_score": 0.0,
            "momentum_12_1": -0.05,
        })
        assert result["final_alpha_score"] <= 0.4

    def test_adjusted_prob_blends(self):
        from app.services.alpha_factor_combiner import AlphaFactorCombiner
        combiner = AlphaFactorCombiner()
        result = combiner.compute(self._make_features(prob=0.7))
        assert result["adjusted_prob_2pct"] is not None
        assert 0.0 <= result["adjusted_prob_2pct"] <= 1.0

    def test_decay_functions(self):
        from app.services.alpha_factor_combiner import pead_decay, momentum_decay, squeeze_decay
        # PEAD: 1.0 at 0 weeks, 0.0 at 6 weeks
        assert pead_decay(0) == pytest.approx(1.0)
        assert pead_decay(6) == pytest.approx(0.0)
        # Momentum: exponential, > 0 always, decays slowly
        assert 0.5 < momentum_decay(18) < 1.0
        assert momentum_decay(0) == pytest.approx(1.0)
        # Squeeze: fast decay
        assert squeeze_decay(0) == pytest.approx(1.0)
        assert squeeze_decay(2) == pytest.approx(0.0)
        assert squeeze_decay(1) == pytest.approx(0.5)

    def test_conviction_labels(self):
        from app.services.alpha_factor_combiner import AlphaFactorCombiner
        combiner = AlphaFactorCombiner()
        # All negative → no signal
        r_none = combiner.compute({"mom_lowvol_score": -2.0})
        assert r_none["conviction_label"] == "NONE"
        # Strong positive alignment
        r_hc = combiner.compute(self._make_features(mlv=2.5, pead_str=4.5, squeeze=3.5, mom12=0.15))
        assert r_hc["conviction_label"] in ("HIGH_CONVICTION", "STRONG", "MODERATE")

    def test_compute_features_only_subset(self):
        from app.services.alpha_factor_combiner import AlphaFactorCombiner, ALPHA_COMBO_FEATURES
        combiner = AlphaFactorCombiner()
        result = combiner.compute_features_only(self._make_features())
        assert set(result.keys()) == set(ALPHA_COMBO_FEATURES)
