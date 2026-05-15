#!/usr/bin/env python3
"""Backup the models_store directory as a compressed tar.gz archive.

Usage:
    python scripts/backup_models.py [--output-dir ./backups] [--retention 7]
"""

from __future__ import annotations

import argparse
import logging
import sys
import tarfile
from datetime import datetime, timedelta
from pathlib import Path

# Ensure backend is on sys.path when run standalone
ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("backup_models")


def run_models_backup(output_dir: Path, retention_days: int) -> Path:
    """Create a timestamped tar.gz of the models_store directory.

    Returns the path to the created archive.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    models_dir = Path(settings.models_dir)
    if not models_dir.exists():
        raise FileNotFoundError(f"Models directory not found: {models_dir}")

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"models_backup_{timestamp}.tar.gz"
    out_path = output_dir / filename

    logger.info("Archiving %s → %s", models_dir, out_path)
    with tarfile.open(out_path, "w:gz") as tar:
        tar.add(models_dir, arcname=models_dir.name)

    logger.info("Models backup complete: %s (%s bytes)", out_path, out_path.stat().st_size)

    # Retention cleanup
    cutoff = datetime.utcnow() - timedelta(days=retention_days)
    removed = 0
    for f in sorted(output_dir.glob("models_backup_*.tar.gz")):
        try:
            ts_str = f.stem.replace("models_backup_", "")
            ftime = datetime.strptime(ts_str, "%Y%m%d_%H%M%S")
            if ftime < cutoff:
                f.unlink()
                removed += 1
        except ValueError:
            continue

    if removed:
        logger.info("Retention cleanup removed %d old archive(s)", removed)

    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Borsa Models Store Backup")
    parser.add_argument(
        "--output-dir",
        default=settings.backup_dir or "./backups",
        help="Directory to store backup archives",
    )
    parser.add_argument(
        "--retention",
        type=int,
        default=settings.backup_retention_days or 7,
        help="Number of days to retain backups",
    )
    args = parser.parse_args()

    try:
        path = run_models_backup(Path(args.output_dir), args.retention)
        print(f"Models backup created: {path}")
        return 0
    except Exception as exc:
        logger.error("Models backup failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
