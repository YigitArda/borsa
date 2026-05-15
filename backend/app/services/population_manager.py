"""
Population-based parallel strategy search.

Manages a population of strategy configs, evolves them in parallel via Celery,
and culls duplicates using Jaccard similarity.

Population lifecycle:
  1. seed(base_config, n)         — initialize with mutations of base
  2. evolve(n_generations)        — parallel evaluate + select + crossover
  3. best()                       — return top Individual by fitness
  4. diversity_score()            — mean pairwise Jaccard distance

Parallelism: each individual evaluated as a Celery task (group/chord).
Fallback: if Celery not available, evaluates sequentially.
"""
from __future__ import annotations

import copy
import logging
import random
from typing import Callable

import numpy as np

from app.services.genetic_evolver import (
    Individual,
    crossover,
    enforce_diversity,
    fitness,
    jaccard_similarity,
    tournament_select,
    POPULATION_SIZE,
    ELITE_N,
    TOURNAMENT_K,
)

logger = logging.getLogger(__name__)

MAX_GENERATIONS = 10
DIVERSITY_CULL_THRESHOLD = 0.80


class PopulationManager:
    """
    Manages a population of strategy configs for parallel search.

    Usage:
        pm = PopulationManager(evaluate_fn, n=10)
        pm.seed(base_config)
        pm.evolve(n_generations=5)
        best = pm.best()
    """

    def __init__(
        self,
        evaluate_fn: Callable[[dict], tuple[list[dict], int | None]],
        n: int = POPULATION_SIZE,
    ):
        self.evaluate = evaluate_fn
        self.n = n
        self.population: list[Individual] = []
        self._generation = 0

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def seed(self, base_config: dict) -> None:
        """Initialize population by mutating base_config N times."""
        from app.services.research_loop import StrategyProposer
        proposer = StrategyProposer()
        self.population = [Individual(config=copy.deepcopy(base_config))]
        while len(self.population) < self.n:
            mutated = proposer.propose(copy.deepcopy(base_config))
            self.population.append(Individual(config=mutated))
        logger.info("PopulationManager: seeded %d individuals", len(self.population))

    # ------------------------------------------------------------------
    # Evaluation (parallel via Celery, sequential fallback)
    # ------------------------------------------------------------------

    def _evaluate_parallel(self, individuals: list[Individual]) -> list[Individual]:
        """Evaluate individuals in parallel using Celery group."""
        try:
            from celery import group
            from app.tasks.pipeline_tasks import evaluate_individual_task

            jobs = group(
                evaluate_individual_task.s(ind.config) for ind in individuals
            )
            results = jobs.apply_async().get(timeout=3600)

            evaluated = []
            for ind, result in zip(individuals, results):
                fold_metrics, strategy_id = result
                ind.fold_metrics = fold_metrics
                ind.strategy_id = strategy_id
                ind.recompute_fitness()
                evaluated.append(ind)
            return evaluated

        except Exception as exc:
            logger.warning("Parallel evaluation failed (%s) — falling back to sequential", exc)
            return self._evaluate_sequential(individuals)

    def _evaluate_sequential(self, individuals: list[Individual]) -> list[Individual]:
        for ind in individuals:
            try:
                fold_metrics, strategy_id = self.evaluate(ind.config)
                ind.fold_metrics = fold_metrics
                ind.strategy_id = strategy_id
                ind.recompute_fitness()
            except Exception as exc:
                logger.warning("Individual eval failed: %s", exc)
                ind.fitness_score = 0.0
        return individuals

    # ------------------------------------------------------------------
    # Evolution
    # ------------------------------------------------------------------

    def evolve(self, n_generations: int = 5, use_celery: bool = True) -> None:
        """
        Run population evolution for N generations.

        Elitism: top ELITE_N survive unchanged.
        Selection: tournament (k=3).
        Crossover + mutate for remaining slots.
        Diversity: cull individuals with Jaccard > 0.80.
        """
        from app.services.research_loop import StrategyProposer
        proposer = StrategyProposer()

        # Evaluate initial population
        unevaluated = [ind for ind in self.population if ind.strategy_id is None]
        if unevaluated:
            logger.info("PopulationManager: evaluating initial %d individuals", len(unevaluated))
            evaluated = (
                self._evaluate_parallel(unevaluated) if use_celery
                else self._evaluate_sequential(unevaluated)
            )
            # Merge back
            eval_map = {id(ind): ind for ind in evaluated}
            self.population = [eval_map.get(id(ind), ind) for ind in self.population]

        for gen in range(n_generations):
            self._generation += 1
            self.population.sort(key=lambda x: x.fitness_score, reverse=True)

            # Elites survive
            next_gen: list[Individual] = self.population[:ELITE_N]
            next_gen = enforce_diversity(next_gen)

            # Fill with offspring
            while len(next_gen) < self.n:
                pa = tournament_select(self.population, TOURNAMENT_K)
                pb = tournament_select(self.population, TOURNAMENT_K)
                child = crossover(pa, pb)
                child.config = proposer.propose(child.config)
                next_gen.append(child)

            # Evaluate new (unevaluated) individuals
            new_inds = [ind for ind in next_gen if ind.strategy_id is None]
            if new_inds:
                evaluated = (
                    self._evaluate_parallel(new_inds) if use_celery
                    else self._evaluate_sequential(new_inds)
                )
                eval_map = {id(ind): ind for ind in evaluated}
                next_gen = [eval_map.get(id(ind), ind) for ind in next_gen]

            # Diversity enforcement
            next_gen = enforce_diversity(next_gen)

            self.population = next_gen
            best = self.best()
            logger.info(
                "PopulationManager gen %d: best_fitness=%.4f (strategy_id=%s) pop=%d",
                self._generation,
                best.fitness_score if best else 0.0,
                best.strategy_id if best else None,
                len(self.population),
            )

    # ------------------------------------------------------------------
    # Results
    # ------------------------------------------------------------------

    def best(self) -> Individual | None:
        if not self.population:
            return None
        return max(self.population, key=lambda x: x.fitness_score)

    def diversity_score(self) -> float:
        """Mean pairwise Jaccard distance (1 - similarity) across population."""
        if len(self.population) < 2:
            return 1.0
        distances = []
        for i, a in enumerate(self.population):
            for b in self.population[i + 1:]:
                sim = jaccard_similarity(
                    a.config.get("features", []),
                    b.config.get("features", []),
                )
                distances.append(1.0 - sim)
        return round(float(np.mean(distances)), 4) if distances else 1.0

    def summary(self) -> dict:
        """Population summary statistics."""
        if not self.population:
            return {"n": 0}
        fitnesses = [ind.fitness_score for ind in self.population]
        return {
            "generation": self._generation,
            "n": len(self.population),
            "best_fitness": round(max(fitnesses), 4),
            "avg_fitness": round(float(np.mean(fitnesses)), 4),
            "diversity_score": self.diversity_score(),
            "best_strategy_id": self.best().strategy_id if self.best() else None,
        }
