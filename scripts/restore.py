#!/usr/bin/env python3
"""PostgreSQL restore script with backup listing and point-in-time selection.

Usage:
    python scripts/restore.py --list
    python scripts/restore.py --file backups/borsa_backup_20260515_080000.sql.gz
"""

from __future__ import annotations

import argparse
import gzip
import logging
import os
import subprocess
import sys
from datetime import datetime
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
logger = logging.getLogger("restore")


def _psql_path() -> str:
    bin_dir = os.getenv("POSTGRES_BIN", "")
    return os.path.join(bin_dir, "psql") if bin_dir else "psql"


def _parse_db_url(url: str) -> dict[str, str]:
    rest = url.replace("postgresql+asyncpg://", "postgresql://").replace("postgresql://", "")
    creds, _, rest = rest.partition("@")
    user, _, password = creds.partition(":")
    host_port, _, db = rest.partition("/")
    host, _, port = host_port.partition(":")
    return {
        "user": user,
        "password": password,
        "host": host or "localhost",
        "port": port or "5432",
        "dbname": db.split("?")[0],
    }


def list_backups(backup_dir: Path) -> list[Path]:
    """Return sorted list of available backup files (newest first)."""
    files = sorted(backup_dir.glob("borsa_backup_*.sql.gz"), reverse=True)
    return files


def restore_backup(file_path: Path) -> None:
    """Restore a gzipped SQL dump into the configured database."""
    if not file_path.exists():
        raise FileNotFoundError(f"Backup file not found: {file_path}")

    db = _parse_db_url(settings.sync_database_url)
    psql = _psql_path()

    cmd = [
        psql,
        "--host", db["host"],
        "--port", db["port"],
        "--username", db["user"],
        "--dbname", db["dbname"],
        "--set", "ON_ERROR_STOP=on",
        "--quiet",
    ]

    env = os.environ.copy()
    env["PGPASSWORD"] = db["password"]

    logger.info("Restoring from %s", file_path)
    with gzip.open(file_path, "rb") as gz:
        proc = subprocess.Popen(
            cmd,
            stdin=gz,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        stdout, stderr = proc.communicate()

    if proc.returncode != 0:
        raise RuntimeError(f"psql restore failed (rc={proc.returncode}): {stderr.decode()}")

    logger.info("Restore completed successfully")


def restore_point_in_time(backup_dir: Path, target: datetime) -> None:
    """Pick the newest backup that is <= target and restore it."""
    files = list_backups(backup_dir)
    chosen: Path | None = None
    for f in files:
        try:
            ts_str = f.stem.replace("borsa_backup_", "").replace(".sql", "")
            ftime = datetime.strptime(ts_str, "%Y%m%d_%H%M%S")
            if ftime <= target:
                chosen = f
                break
        except ValueError:
            continue

    if chosen is None:
        raise RuntimeError(f"No backup found on or before {target.isoformat()}")

    logger.info("Point-in-time target %s — selected backup %s", target, chosen.name)
    restore_backup(chosen)


def main() -> int:
    parser = argparse.ArgumentParser(description="Borsa PostgreSQL Restore")
    parser.add_argument(
        "--backup-dir",
        default=settings.backup_dir or "./backups",
        help="Directory containing backup files",
    )
    parser.add_argument("--list", action="store_true", help="List available backups")
    parser.add_argument("--file", type=Path, help="Specific backup file to restore")
    parser.add_argument(
        "--point-in-time",
        help="Restore to the newest backup on or before this ISO timestamp",
    )
    args = parser.parse_args()

    backup_dir = Path(args.backup_dir)

    if args.list:
        files = list_backups(backup_dir)
        if not files:
            print("No backups found.")
            return 0
        print(f"{'Index':<6} {'Timestamp':<20} {'Size (bytes)':<15} {'File'}")
        print("-" * 70)
        for idx, f in enumerate(files, 1):
            ts_str = f.stem.replace("borsa_backup_", "").replace(".sql", "")
            size = f.stat().st_size
            print(f"{idx:<6} {ts_str:<20} {size:<15} {f.name}")
        return 0

    if args.file:
        try:
            restore_backup(args.file)
            return 0
        except Exception as exc:
            logger.error("Restore failed: %s", exc)
            return 1

    if args.point_in_time:
        try:
            target = datetime.fromisoformat(args.point_in_time)
            restore_point_in_time(backup_dir, target)
            return 0
        except Exception as exc:
            logger.error("Restore failed: %s", exc)
            return 1

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
