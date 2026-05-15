"""
Price Tokenization and NLP Features.

4A: SAX (Symbolic Aggregate Approximation) — price series → letter sequence
4B: N-gram frequency analysis — pattern hit rates
4C: Price embedding — word2vec-style price pattern embeddings (lightweight)

SAX alphabet: A(very low) B(low) C(mid) D(high) E(very high)
Breakpoints: quintiles of weekly returns computed from trailing 52w window.

N-gram lookup:
  For each observed N-gram, count how often it was followed by:
    - return >= +2% next week (bullish)
    - return <= -2% next week (bearish)
  Hit rate stored in-memory (rebuilt per stock from weekly data).

Performance target: 20 stocks × 500 weeks < 5 seconds total.

Lookahead guarantee: N-gram patterns are built only from historical data
before the prediction week. The N-gram at week T uses only weeks ≤ T-1.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Literal

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

ALPHABET = "ABCDE"  # 5 symbols (quintiles)
N_GRAM_LENGTH = 3   # default window
MIN_OCCURRENCES = 5  # minimum N-gram occurrences to compute a reliable hit rate

PRICE_NLP_FEATURES = [
    "ngram_bullish_score",    # ∈ [0,1]: how often this pattern preceded +2% next week
    "ngram_bearish_score",    # ∈ [0,1]: how often this pattern preceded -2% next week
    "ngram_pattern_rarity",   # 1 / log(occurrence_count + 1): rare patterns = less reliable
    "sax_last_symbol",        # ordinal encoding of last SAX symbol (0-4)
    "sax_trend_score",        # ordinal mean of last N symbols: rising = higher score
    "price_embed_dim0",       # first embedding dimension (if Word2Vec fitted)
    "price_embed_dim1",       # second embedding dimension
]


# ---------------------------------------------------------------------------
# 4A: SAX Encoding
# ---------------------------------------------------------------------------

def sax_encode(weekly_returns: pd.Series, window: int = 20, n_symbols: int = 5) -> str:
    """
    Encode the last `window` weekly returns into a SAX string.

    Breakpoints are computed from the trailing 52-week window (no lookahead).

    Args:
        weekly_returns: Sorted ascending weekly return series (no lookahead).
        window:         How many weeks to encode (default 20).
        n_symbols:      Alphabet size (default 5 → A..E).

    Returns:
        SAX string of length min(window, available_weeks). Empty string if < 5 weeks.
    """
    if len(weekly_returns) < 5:
        return ""

    # Use trailing 52 weeks for breakpoints, then encode the last `window` weeks
    reference = weekly_returns.iloc[-52:] if len(weekly_returns) >= 52 else weekly_returns
    breakpoints = np.quantile(reference, np.linspace(0, 1, n_symbols + 1)[1:-1])  # n_symbols-1 cuts

    to_encode = weekly_returns.iloc[-window:] if len(weekly_returns) >= window else weekly_returns
    letters = []
    for val in to_encode:
        if pd.isna(val):
            letters.append("C")  # neutral for NaN
        else:
            idx = int(np.searchsorted(breakpoints, val, side="right"))
            letters.append(ALPHABET[idx])
    return "".join(letters)


def sax_to_features(sax_string: str) -> dict[str, float]:
    """
    Compute scalar features from a SAX string.

    Args:
        sax_string: SAX encoded string.

    Returns:
        sax_last_symbol (0-4), sax_trend_score (mean ordinal of last N).
    """
    if not sax_string:
        return {"sax_last_symbol": 2.0, "sax_trend_score": 2.0}  # neutral

    ordinals = [ALPHABET.index(c) for c in sax_string if c in ALPHABET]
    last_sym = float(ordinals[-1]) if ordinals else 2.0
    trend_score = float(np.mean(ordinals[-5:])) if len(ordinals) >= 5 else float(np.mean(ordinals))

    return {"sax_last_symbol": last_sym, "sax_trend_score": trend_score}


# ---------------------------------------------------------------------------
# 4B: N-gram Frequency Analysis
# ---------------------------------------------------------------------------

class NGramAnalyzer:
    """
    Analyzes historical N-gram patterns and their predictive outcomes.

    For each N-gram observed at week T, records whether next week's return
    was bullish (>=2%) or bearish (<=-2%).

    Usage:
        analyzer = NGramAnalyzer(n=3)
        analyzer.fit(weekly_returns, targets)
        scores = analyzer.score_current(sax_string)
    """

    def __init__(self, n: int = N_GRAM_LENGTH):
        self.n = n
        # {ngram_str: {"bull": int, "bear": int, "total": int}}
        self._ngram_stats: dict[str, dict] = defaultdict(lambda: {"bull": 0, "bear": 0, "total": 0})
        self._fitted = False

    def fit(self, weekly_returns: pd.Series, next_week_returns: pd.Series) -> None:
        """
        Build N-gram lookup table from historical data.

        Args:
            weekly_returns:    Historical weekly returns (no future data).
            next_week_returns: What happened the week AFTER each observation.
                               Must be aligned: next_week_returns[i] follows weekly_returns[i].
        """
        if len(weekly_returns) < self.n + 1:
            return

        aligned = pd.concat([weekly_returns, next_week_returns], axis=1).dropna()
        aligned.columns = ["ret", "next_ret"]

        # Build SAX string for the full history using cumulative windows
        all_sax = []
        for i in range(len(aligned)):
            # Use all available data up to and including row i (no lookahead)
            hist = aligned["ret"].iloc[: i + 1]
            sax = sax_encode(hist, window=len(hist))
            all_sax.append(sax)

        # Extract N-grams and record outcomes
        self._ngram_stats.clear()
        for i, sax in enumerate(all_sax):
            if len(sax) < self.n:
                continue
            ngram = sax[-self.n:]
            next_ret = aligned["next_ret"].iloc[i]
            if pd.isna(next_ret):
                continue
            stats = self._ngram_stats[ngram]
            stats["total"] += 1
            if next_ret >= 0.02:
                stats["bull"] += 1
            elif next_ret <= -0.02:
                stats["bear"] += 1

        self._fitted = True
        logger.debug("NGramAnalyzer: built stats for %d unique N-grams", len(self._ngram_stats))

    def score_current(self, sax_string: str) -> dict[str, float]:
        """
        Compute bullish/bearish scores for the current SAX pattern.

        Args:
            sax_string: Current SAX string (last observation).

        Returns:
            ngram_bullish_score, ngram_bearish_score, ngram_pattern_rarity.
        """
        result = {
            "ngram_bullish_score": 0.5,
            "ngram_bearish_score": 0.5,
            "ngram_pattern_rarity": 1.0,
        }

        if not self._fitted or len(sax_string) < self.n:
            return result

        ngram = sax_string[-self.n:]
        stats = self._ngram_stats.get(ngram)
        if stats is None or stats["total"] < MIN_OCCURRENCES:
            # Pattern never seen or too rare → return neutral + high rarity
            result["ngram_pattern_rarity"] = 1.0
            return result

        total = stats["total"]
        result["ngram_bullish_score"] = round(stats["bull"] / total, 4)
        result["ngram_bearish_score"] = round(stats["bear"] / total, 4)
        result["ngram_pattern_rarity"] = round(1.0 / np.log(total + 1), 4)
        return result


# ---------------------------------------------------------------------------
# 4C: Price Embedding (lightweight Word2Vec-style)
# ---------------------------------------------------------------------------

class PriceEmbedder:
    """
    Lightweight N-gram embedding using co-occurrence counting.

    Maps each SAX N-gram to a 2D embedding via SVD on the co-occurrence matrix.
    This is a simplified alternative to full Word2Vec — no neural network needed.

    Usage:
        embedder = PriceEmbedder(n=3, embed_dim=2)
        embedder.fit(list_of_sax_strings)
        vec = embedder.embed(current_sax_string)
    """

    def __init__(self, n: int = N_GRAM_LENGTH, embed_dim: int = 2):
        self.n = n
        self.embed_dim = embed_dim
        self._embeddings: dict[str, np.ndarray] = {}
        self._fitted = False

    def fit(self, sax_sequences: list[str], context_window: int = 2) -> None:
        """
        Build embeddings from a list of SAX sequences via co-occurrence + SVD.

        Args:
            sax_sequences:  List of SAX strings (one per stock or time window).
            context_window: Context for co-occurrence (default 2).
        """
        # Collect all unique N-grams
        all_ngrams: list[str] = []
        for seq in sax_sequences:
            if len(seq) >= self.n:
                all_ngrams.extend([seq[i: i + self.n] for i in range(len(seq) - self.n + 1)])

        vocab = sorted(set(all_ngrams))
        if len(vocab) < self.embed_dim + 1:
            return

        idx = {g: i for i, g in enumerate(vocab)}
        cooc = np.zeros((len(vocab), len(vocab)), dtype=float)

        for seq in sax_sequences:
            ngrams = [seq[i: i + self.n] for i in range(len(seq) - self.n + 1)]
            for i, gram in enumerate(ngrams):
                for j in range(max(0, i - context_window), min(len(ngrams), i + context_window + 1)):
                    if i != j:
                        cooc[idx[gram], idx[ngrams[j]]] += 1.0

        # SVD to get low-dim embeddings
        from numpy.linalg import svd
        U, S, Vt = svd(cooc, full_matrices=False)
        embed_matrix = U[:, : self.embed_dim] * S[: self.embed_dim]

        for i, gram in enumerate(vocab):
            self._embeddings[gram] = embed_matrix[i]

        self._fitted = True
        logger.debug("PriceEmbedder: fitted %d N-gram embeddings (dim=%d)", len(vocab), self.embed_dim)

    def embed(self, sax_string: str) -> np.ndarray:
        """
        Get embedding for the current SAX pattern (last N-gram).

        Returns zero vector if not fitted or pattern unseen.
        """
        if not self._fitted or len(sax_string) < self.n:
            return np.zeros(self.embed_dim)
        ngram = sax_string[-self.n:]
        return self._embeddings.get(ngram, np.zeros(self.embed_dim))

    def embed_to_features(self, sax_string: str) -> dict[str, float]:
        vec = self.embed(sax_string)
        return {
            "price_embed_dim0": round(float(vec[0]), 6) if len(vec) > 0 else 0.0,
            "price_embed_dim1": round(float(vec[1]), 6) if len(vec) > 1 else 0.0,
        }


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

class PriceNLPService:
    """
    Computes all price NLP features for one stock.

    Usage:
        svc = PriceNLPService()
        svc.fit(weekly_returns, next_week_returns)
        features = svc.compute(weekly_returns)
    """

    def __init__(self, n: int = N_GRAM_LENGTH):
        self.n = n
        self._ngram = NGramAnalyzer(n=n)
        self._embedder = PriceEmbedder(n=n, embed_dim=2)
        self._fitted = False

    def fit(self, weekly_returns: pd.Series, next_week_returns: pd.Series) -> None:
        """Fit both N-gram analyzer and embedder."""
        self._ngram.fit(weekly_returns, next_week_returns)

        # Build SAX sequences for embedding
        sax_seqs = []
        for end_idx in range(self.n, len(weekly_returns)):
            hist = weekly_returns.iloc[:end_idx]
            sax = sax_encode(hist, window=min(52, len(hist)))
            if len(sax) >= self.n:
                sax_seqs.append(sax)
        if sax_seqs:
            self._embedder.fit(sax_seqs)

        self._fitted = True

    def compute(self, weekly_returns: pd.Series) -> dict[str, float]:
        """
        Compute all price NLP features for the current observation.

        Args:
            weekly_returns: Available weekly returns up to (not including) prediction week.

        Returns:
            Dict with all PRICE_NLP_FEATURES values.
        """
        result: dict[str, float] = {f: np.nan for f in PRICE_NLP_FEATURES}

        sax_string = sax_encode(weekly_returns, window=20)
        result.update(sax_to_features(sax_string))

        if self._fitted:
            result.update(self._ngram.score_current(sax_string))
            result.update(self._embedder.embed_to_features(sax_string))
        else:
            result["ngram_bullish_score"] = 0.5
            result["ngram_bearish_score"] = 0.5
            result["ngram_pattern_rarity"] = 1.0
            result["price_embed_dim0"] = 0.0
            result["price_embed_dim1"] = 0.0

        return result
