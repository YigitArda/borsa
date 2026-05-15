"""Trinity screener for pre-explosion equity discovery.

Combines information geometry, Shannon entropy and Lempel-Ziv complexity.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd
from scipy.ndimage import gaussian_filter1d

logger = logging.getLogger(__name__)


@dataclass
class TrinityScore:
    ticker: str
    fisher_curvature: float
    shannon_entropy: float
    lz_complexity: float
    combined_score: float
    regime: str
    rank: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


class InformationGeometryEngine:
    """Compute Fisher information and a curvature proxy from returns."""

    def __init__(self, window: int = 60, n_bins: int = 50):
        self.window = window
        self.n_bins = n_bins

    def compute_metric(self, returns: pd.Series) -> np.ndarray:
        recent = pd.Series(returns, dtype=float).dropna().iloc[-self.window :]
        if len(recent) < max(10, int(self.window * 0.5)):
            return np.eye(1) * 1e-6

        hist, bin_edges = np.histogram(recent, bins=min(self.n_bins, len(recent)), density=True)
        if len(hist) == 0 or len(bin_edges) < 2:
            return np.eye(1) * 1e-6
        centers = (bin_edges[:-1] + bin_edges[1:]) / 2.0
        smooth_hist = gaussian_filter1d(hist.astype(float), sigma=1.0)
        smooth_hist = np.maximum(smooth_hist, 1e-10)
        step = centers[1] - centers[0] if len(centers) > 1 else 1.0
        score = np.gradient(np.log(smooth_hist), step)
        fisher = np.sum(smooth_hist * score**2) * abs(step)
        return np.array([[float(max(fisher, 1e-12))]])

    def curvature(self, returns: pd.Series) -> float:
        metric = self.compute_metric(returns)
        return float(np.log1p(np.linalg.det(metric)))


class EntropyEngine:
    """Normalized Shannon entropy of recent returns."""

    def __init__(self, bins: int = 50, window: int = 20):
        self.bins = bins
        self.window = window

    def shannon_entropy(self, returns: pd.Series) -> float:
        recent = pd.Series(returns, dtype=float).dropna().iloc[-self.window :]
        if len(recent) < 10:
            return 1.0

        hist, _ = np.histogram(recent, bins=min(self.bins, len(recent)), density=False)
        total = hist.sum()
        if total <= 0:
            return 1.0
        probabilities = hist[hist > 0] / total
        entropy = -np.sum(probabilities * np.log2(probabilities))
        max_entropy = np.log2(max(2, min(self.bins, len(recent))))
        return float(np.clip(entropy / max_entropy, 0.0, 1.0))

    def approximate_entropy(self, returns: pd.Series, m: int = 2, r: float | None = None) -> float:
        recent = pd.Series(returns, dtype=float).dropna().iloc[-self.window :].to_numpy()
        n = len(recent)
        if n < m + 10:
            return 1.0
        if r is None:
            r = 0.2 * float(np.std(recent))
        if r == 0:
            return 0.0

        def phi(order: int) -> float:
            patterns = np.array([recent[i : i + order] for i in range(n - order + 1)])
            counts = []
            for pattern in patterns:
                distance = np.max(np.abs(patterns - pattern), axis=1)
                counts.append(np.mean(distance <= r))
            counts = np.maximum(np.asarray(counts), 1e-12)
            return float(np.mean(np.log(counts)))

        return float(abs(phi(m) - phi(m + 1)))


class ComplexityEngine:
    """Approximate Kolmogorov complexity with Lempel-Ziv parsing."""

    def __init__(self, window: int = 60):
        self.window = window

    def lz77_complexity(self, returns: pd.Series) -> float:
        recent = pd.Series(returns, dtype=float).dropna().iloc[-self.window :]
        if len(recent) < 20:
            return 1.0

        binary = "".join("1" if value > 0 else "0" for value in recent)
        n = len(binary)
        complexity = 1
        i = 1
        while i < n:
            complexity += 1
            max_match = 0
            for j in range(i):
                match_len = 0
                while (
                    i + match_len < n
                    and j + match_len < i
                    and binary[j + match_len] == binary[i + match_len]
                ):
                    match_len += 1
                max_match = max(max_match, match_len)
            i += max(1, max_match)

        max_theoretical = n / max(1.0, np.log2(n))
        return float(np.clip(complexity / max_theoretical, 0.0, 1.0))

    def lempel_ziv_normalization(self, returns: pd.Series) -> float:
        return float(1.0 - self.lz77_complexity(returns))


class TrinityScreener:
    """Rank equities by low entropy, low complexity and constructive curvature."""

    def __init__(
        self,
        entropy_threshold: float = 0.40,
        complexity_threshold: float = 0.30,
        curvature_min: float = -2.0,
        curvature_max: float = 5.0,
    ):
        self.entropy_thresh = entropy_threshold
        self.complexity_thresh = complexity_threshold
        self.curvature_min = curvature_min
        self.curvature_max = curvature_max
        self.ig_engine = InformationGeometryEngine()
        self.ent_engine = EntropyEngine()
        self.comp_engine = ComplexityEngine()

    def screen_universe(
        self,
        price_data: dict[str, pd.DataFrame],
        fundamentals: dict[str, dict] | None = None,
    ) -> list[TrinityScore]:
        scores: list[TrinityScore] = []
        for ticker, df in price_data.items():
            try:
                if df is None or len(df) < 60 or "close" not in df:
                    continue
                returns = pd.Series(df["close"], dtype=float).pct_change().dropna()
                if len(returns) < 30:
                    continue

                curvature = self.ig_engine.curvature(returns)
                entropy = self.ent_engine.shannon_entropy(returns)
                complexity = self.comp_engine.lz77_complexity(returns)
                regime = self._classify_regime(entropy, complexity, curvature, returns)

                curvature_score = 1.0 - abs(curvature - 1.5) / 3.0
                curvature_score = float(np.clip(curvature_score, 0.0, 1.0))
                combined = (
                    0.4 * (1.0 - entropy)
                    + 0.3 * (1.0 - complexity)
                    + 0.3 * curvature_score
                )

                if fundamentals and ticker in fundamentals:
                    data = fundamentals[ticker]
                    if data.get("insider_buying_ratio", 1.0) > 2.0:
                        combined *= 1.15
                    if data.get("institutional_change", 0.0) > 0.05:
                        combined *= 1.10

                scores.append(
                    TrinityScore(
                        ticker=ticker,
                        fisher_curvature=float(curvature),
                        shannon_entropy=float(entropy),
                        lz_complexity=float(complexity),
                        combined_score=float(np.clip(combined, 0.0, 1.5)),
                        regime=regime,
                    )
                )
            except Exception as exc:
                logger.warning("Error screening %s: %s", ticker, exc)

        scores.sort(key=lambda item: item.combined_score, reverse=True)
        for rank, score in enumerate(scores, start=1):
            score.rank = rank
        return scores

    def filter_pre_explosion(
        self,
        scores: list[TrinityScore],
        price_data: dict[str, pd.DataFrame],
        max_52w_range: tuple[float, float] = (0.40, 0.80),
        min_volume_pct: float = 1.2,
    ) -> list[TrinityScore]:
        filtered = []
        for score in scores:
            if score.combined_score < 0.65:
                continue
            df = price_data.get(score.ticker)
            if df is None or len(df) < 252 or "close" not in df:
                continue
            close = pd.Series(df["close"], dtype=float)
            current = close.iloc[-1]
            high_52w = close.rolling(252, min_periods=100).max().iloc[-1]
            low_52w = close.rolling(252, min_periods=100).min().iloc[-1]
            if high_52w <= low_52w:
                continue
            pct_of_range = (current - low_52w) / (high_52w - low_52w)
            if not (max_52w_range[0] <= pct_of_range <= max_52w_range[1]):
                continue
            if "volume" in df:
                volume = pd.Series(df["volume"], dtype=float)
                vol_20d = volume.rolling(20, min_periods=5).mean().iloc[-1]
                if vol_20d > 0 and volume.iloc[-1] < vol_20d * min_volume_pct:
                    continue
            filtered.append(score)
        return filtered

    def _classify_regime(
        self, entropy: float, complexity: float, curvature: float, returns: pd.Series
    ) -> str:
        recent_mean = float(pd.Series(returns).iloc[-20:].mean()) if len(returns) else 0.0
        if entropy < 0.3 and complexity < 0.2 and curvature > 1.0:
            return "SQUEEZE"
        if entropy < 0.4 and complexity < 0.3 and recent_mean > 0:
            return "TREND"
        if entropy > 0.7 and complexity > 0.6:
            return "CHAOS"
        return "STABLE"
