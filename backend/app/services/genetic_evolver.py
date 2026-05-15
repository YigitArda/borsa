"""
Genetic Algorithm for strategy evolution.

Population: N strategy configs (chromosomes).
Chromosome = frozenset(feature_names) + hyperparams (genes).

Operators:
  crossover(a, b) → child: feature intersection + random extras + averaged hyperparams
  mutate(child)   → uses StrategyProposer.propose()

Fitness: sharpe × profit_factor / (1 + abs(max_drawdown))
Elitism: top 2 survive each generation unchanged.
Tournament selection: k=3 for parent selection.
Diversity: Jaccard similarity > 0.8 → cull one.
"""
from __future__ import annotations

import copy
import logging
import random
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

logger = logging.getLogger(__name__)

POPULATION_SIZE = 10
ELITE_N = 2
TOURNAMENT_K = 3
JACCARD_DIVERSITY_THRESHOLD = 0.80


# ---------------------------------------------------------------------------
# Chromosome helpers
# ---------------------------------------------------------------------------

def jaccard_similarity(a: list[str], b: list[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    return len(sa & sb) / len(sa | sb)


def fitness(metrics: dict) -> float:
    """
    Composite fitness function.
    sharpe × profit_factor / (1 + |max_drawdown|)
    Returns 0.0 if any component is invalid.
    """
    sharpe = metrics.get("sharpe", 0.0) or 0.0
    pf = metrics.get("profit_factor", 0.0) or 0.0
    dd = abs(metrics.get("max_drawdown", 0.0) or 0.0)
    if sharpe <= 0 or pf <= 0:
        return 0.0
    return sharpe * pf / (1.0 + dd)


@dataclass
class Individual:
    config: dict
    fold_metrics: list[dict] = field(default_factory=list)
    fitness_score: float = 0.0
    strategy_id: int | None = None

    def avg_metric(self, key: str) -> float:
        if not self.fold_metrics:
            return 0.0
        vals = [m.get(key, 0.0) for m in self.fold_metrics if m.get(key) is not None]
        return float(np.mean(vals)) if vals else 0.0

    def recompute_fitness(self) -> None:
        self.fitness_score = fitness({
            "sharpe": self.avg_metric("sharpe"),
            "profit_factor": self.avg_metric("profit_factor"),
            "max_drawdown": self.avg_metric("max_drawdown"),
        })


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

def crossover(parent_a: Individual, parent_b: Individual) -> Individual:
    """
    Single-point crossover on feature sets + weighted average on hyperparams.

    Feature chromosome: intersection of both parents + random extra from each.
    Hyperparams: weighted by fitness scores.
    """
    fa = set(parent_a.config.get("features", []))
    fb = set(parent_b.config.get("features", []))

    # Feature crossover: take intersection, add random extras
    core = list(fa & fb)
    extras_a = list(fa - fb)
    extras_b = list(fb - fa)
    random.shuffle(extras_a)
    random.shuffle(extras_b)

    # Add up to half the unique features from each parent
    child_features = core + extras_a[: len(extras_a) // 2 + 1] + extras_b[: len(extras_b) // 2 + 1]
    if not child_features:
        child_features = list(fa | fb)  # fallback: union

    # Hyperparam crossover: weighted average by fitness
    fa_fit = max(parent_a.fitness_score, 1e-6)
    fb_fit = max(parent_b.fitness_score, 1e-6)
    w_a = fa_fit / (fa_fit + fb_fit)
    w_b = 1.0 - w_a

    def _blend_num(key: str, default: float) -> float:
        va = parent_a.config.get(key, default)
        vb = parent_b.config.get(key, default)
        return w_a * (va or default) + w_b * (vb or default)

    child_config = {
        "features": list(dict.fromkeys(child_features)),  # deduplicate, preserve order
        "model_type": parent_a.config["model_type"] if w_a > 0.5 else parent_b.config["model_type"],
        "threshold": round(_blend_num("threshold", 0.5), 3),
        "top_n": max(3, int(round(_blend_num("top_n", 5)))),
        "embargo_weeks": max(2, int(round(_blend_num("embargo_weeks", 4)))),
        "holding_weeks": random.choice([
            parent_a.config.get("holding_weeks", 1),
            parent_b.config.get("holding_weeks", 1),
        ]),
        "target": parent_a.config.get("target", "target_2pct_1w"),
        "stop_loss": random.choice([
            parent_a.config.get("stop_loss"),
            parent_b.config.get("stop_loss"),
        ]),
        "take_profit": random.choice([
            parent_a.config.get("take_profit"),
            parent_b.config.get("take_profit"),
        ]),
    }
    return Individual(config=child_config)


def tournament_select(population: list[Individual], k: int = TOURNAMENT_K) -> Individual:
    """Select parent via k-tournament selection."""
    contestants = random.sample(population, min(k, len(population)))
    return max(contestants, key=lambda ind: ind.fitness_score)


def enforce_diversity(population: list[Individual]) -> list[Individual]:
    """
    Remove individuals with Jaccard similarity > threshold to another individual.
    The one with lower fitness is removed.
    """
    kept = []
    for ind in sorted(population, key=lambda x: x.fitness_score, reverse=True):
        too_similar = False
        for existing in kept:
            sim = jaccard_similarity(
                ind.config.get("features", []),
                existing.config.get("features", []),
            )
            if sim > JACCARD_DIVERSITY_THRESHOLD:
                too_similar = True
                break
        if not too_similar:
            kept.append(ind)
    return kept


# ---------------------------------------------------------------------------
# GeneticEvolver
# ---------------------------------------------------------------------------

class GeneticEvolver:
    """
    Population-based genetic algorithm for strategy evolution.

    Usage:
        evolver = GeneticEvolver(session, tickers, evaluate_fn)
        best = evolver.evolve(base_config, n_generations=5)
    """

    def __init__(
        self,
        evaluate_fn: Callable[[dict], tuple[list[dict], int | None]],
        n: int = POPULATION_SIZE,
    ):
        """
        Args:
            evaluate_fn: Callable(config) → (fold_metrics_list, strategy_id).
                         Runs walk-forward and returns fold results.
            n: Population size.
        """
        self.evaluate = evaluate_fn
        self.n = n

    def _init_population(self, base_config: dict) -> list[Individual]:
        """Initialize population by mutating base_config N times."""
        from app.services.research_loop import StrategyProposer
        proposer = StrategyProposer()
        population = [Individual(config=copy.deepcopy(base_config))]
        while len(population) < self.n:
            mutated = proposer.propose(copy.deepcopy(base_config))
            population.append(Individual(config=mutated))
        return population

    def _evaluate_individual(self, ind: Individual) -> Individual:
        """Run walk-forward for one individual and compute fitness."""
        try:
            fold_metrics, strategy_id = self.evaluate(ind.config)
            ind.fold_metrics = fold_metrics
            ind.strategy_id = strategy_id
            ind.recompute_fitness()
        except Exception as exc:
            logger.warning("Genetic eval failed: %s", exc)
            ind.fitness_score = 0.0
        return ind

    def evolve(self, base_config: dict, n_generations: int = 5) -> Individual:
        """
        Run the genetic algorithm.

        Returns the best Individual found across all generations.
        """
        from app.services.research_loop import StrategyProposer
        proposer = StrategyProposer()

        population = self._init_population(base_config)

        # Evaluate initial population
        logger.info("Genetic: evaluating initial population (%d individuals)", len(population))
        population = [self._evaluate_individual(ind) for ind in population]

        best_ever = max(population, key=lambda x: x.fitness_score)
        logger.info("Genetic gen 0: best fitness=%.4f", best_ever.fitness_score)

        for gen in range(1, n_generations + 1):
            # Sort by fitness
            population.sort(key=lambda x: x.fitness_score, reverse=True)

            # Elitism: top ELITE_N survive
            next_gen: list[Individual] = population[:ELITE_N]

            # Diversity enforcement on elite
            next_gen = enforce_diversity(next_gen)

            # Fill the rest with offspring
            while len(next_gen) < self.n:
                parent_a = tournament_select(population)
                parent_b = tournament_select(population)
                child = crossover(parent_a, parent_b)
                child.config = proposer.propose(child.config)  # mutate
                next_gen.append(child)

            # Evaluate new individuals only
            for i, ind in enumerate(next_gen):
                if ind.strategy_id is None:  # not yet evaluated
                    next_gen[i] = self._evaluate_individual(ind)

            # Diversity enforcement on full next_gen
            next_gen = enforce_diversity(next_gen)

            population = next_gen
            gen_best = max(population, key=lambda x: x.fitness_score)
            if gen_best.fitness_score > best_ever.fitness_score:
                best_ever = gen_best

            logger.info(
                "Genetic gen %d: best_fitness=%.4f (strategy_id=%s) pop_size=%d",
                gen, gen_best.fitness_score, gen_best.strategy_id, len(population),
            )

        logger.info("Genetic done: best_ever fitness=%.4f strategy_id=%s",
                    best_ever.fitness_score, best_ever.strategy_id)
        return best_ever

    def generation_summary(self, population: list[Individual]) -> dict:
        """Return summary dict for a generation."""
        fitnesses = [ind.fitness_score for ind in population]
        return {
            "n": len(population),
            "best_fitness": round(max(fitnesses), 4) if fitnesses else 0.0,
            "avg_fitness": round(float(np.mean(fitnesses)), 4) if fitnesses else 0.0,
            "best_strategy_id": max(population, key=lambda x: x.fitness_score).strategy_id if population else None,
        }
