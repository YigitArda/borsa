"""
Model Registry and Versioning service.

Enforces immutability of model artifacts and tracks the full lifecycle
of every trained model version from research → candidate → paper_trading
→ promoted → archived.
"""
from __future__ import annotations

import hashlib
import logging
import os
from typing import Any

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.strategy import ModelVersion

logger = logging.getLogger(__name__)

VALID_STATUSES = {
    "research",
    "candidate",
    "paper_trading",
    "promoted",
    "archived",
}

TRANSITIONS: dict[str, set[str]] = {
    "research": {"candidate", "archived"},
    "candidate": {"paper_trading", "archived"},
    "paper_trading": {"promoted", "archived"},
    "promoted": {"archived"},
    "archived": set(),
}


class ModelRegistry:
    """Central registry for model versions."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _compute_file_hash(path: str) -> str | None:
        """Return SHA-256 hex digest of a file, or None if missing."""
        if not path or not os.path.isfile(path):
            return None
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def _status_transition_allowed(current: str, target: str) -> bool:
        return target in TRANSITIONS.get(current, set())

    # ------------------------------------------------------------------
    # CRUD / Lifecycle
    # ------------------------------------------------------------------
    async def register_model(
        self,
        strategy_id: int,
        model_path: str,
        metadata: dict[str, Any] | None = None,
    ) -> ModelVersion:
        """Register a new model version. Status is always 'research'."""
        metadata = metadata or {}

        # Immutability guard – refuse to overwrite an existing artifact
        if model_path and os.path.exists(model_path):
            existing = await self.db.execute(
                select(ModelVersion).where(ModelVersion.model_path == model_path)
            )
            if existing.scalar_one_or_none() is not None:
                raise FileExistsError(
                    f"Model file already registered: {model_path}. "
                    "Model artifacts are immutable."
                )

        file_hash = self._compute_file_hash(model_path)

        mv = ModelVersion(
            strategy_id=strategy_id,
            model_path=model_path,
            status="research",
            feature_set_version=metadata.get("feature_set_version"),
            train_start=metadata.get("train_start"),
            train_end=metadata.get("train_end"),
            metrics=metadata.get("metrics"),
            holdout_period=metadata.get("holdout_period"),
            validation_period=metadata.get("validation_period"),
            parent_model_id=metadata.get("parent_model_id"),
            hyperparams=metadata.get("hyperparams"),
            model_file_hash=file_hash,
        )
        self.db.add(mv)
        await self.db.commit()
        await self.db.refresh(mv)
        logger.info("Registered model version %s for strategy %s", mv.id, strategy_id)
        return mv

    async def promote_model(
        self,
        model_version_id: int,
        reason: str | None = None,
    ) -> ModelVersion:
        """Promote a model version to 'promoted' status."""
        mv = await self.db.get(ModelVersion, model_version_id)
        if mv is None:
            raise ValueError(f"ModelVersion {model_version_id} not found")

        if not self._status_transition_allowed(mv.status, "promoted"):
            raise ValueError(
                f"Cannot promote model from status '{mv.status}' to 'promoted'"
            )

        await self.validate_immutable(model_version_id)

        mv.status = "promoted"
        mv.promotion_reason = reason
        await self.db.commit()
        await self.db.refresh(mv)
        logger.info("Promoted model version %s", mv.id)
        return mv

    async def archive_model(
        self,
        model_version_id: int,
        reason: str | None = None,
    ) -> ModelVersion:
        """Archive a model version."""
        mv = await self.db.get(ModelVersion, model_version_id)
        if mv is None:
            raise ValueError(f"ModelVersion {model_version_id} not found")

        if not self._status_transition_allowed(mv.status, "archived"):
            raise ValueError(
                f"Cannot archive model from status '{mv.status}'"
            )

        mv.status = "archived"
        mv.rejection_reason = reason
        await self.db.commit()
        await self.db.refresh(mv)
        logger.info("Archived model version %s", mv.id)
        return mv

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    async def get_model_chain(
        self,
        model_version_id: int,
    ) -> list[ModelVersion]:
        """Return the full parent chain for a model version (oldest → newest)."""
        chain: list[ModelVersion] = []
        visited: set[int] = set()
        current_id = model_version_id

        while current_id is not None and current_id not in visited:
            mv = await self.db.get(ModelVersion, current_id)
            if mv is None:
                break
            visited.add(current_id)
            chain.append(mv)
            current_id = mv.parent_model_id

        # Reverse so the chain reads oldest → newest (target model last)
        chain.reverse()
        return chain

    async def get_latest_promoted(
        self,
        strategy_id: int,
    ) -> ModelVersion | None:
        """Return the most recently created promoted model for a strategy."""
        result = await self.db.execute(
            select(ModelVersion)
            .where(
                ModelVersion.strategy_id == strategy_id,
                ModelVersion.status == "promoted",
            )
            .order_by(desc(ModelVersion.created_at))
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_all_versions(
        self,
        strategy_id: int,
    ) -> list[ModelVersion]:
        """Return all model versions for a strategy, newest first."""
        result = await self.db.execute(
            select(ModelVersion)
            .where(ModelVersion.strategy_id == strategy_id)
            .order_by(desc(ModelVersion.created_at))
        )
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Integrity
    # ------------------------------------------------------------------
    async def validate_immutable(self, model_version_id: int) -> bool:
        """
        Ensure the on-disk model file has not been altered since registration.
        Returns True if intact, raises RuntimeError if corrupted / overwritten.
        """
        mv = await self.db.get(ModelVersion, model_version_id)
        if mv is None:
            raise ValueError(f"ModelVersion {model_version_id} not found")

        if not mv.model_path or not mv.model_file_hash:
            # Nothing to validate
            return True

        current_hash = self._compute_file_hash(mv.model_path)
        if current_hash is None:
            raise RuntimeError(
                f"Model file missing for version {model_version_id}: {mv.model_path}"
            )

        if current_hash != mv.model_file_hash:
            raise RuntimeError(
                f"Model file hash mismatch for version {model_version_id}. "
                f"Expected {mv.model_file_hash}, got {current_hash}. "
                "Model artifacts must remain immutable."
            )

        return True
