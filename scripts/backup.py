#!/usr/bin/env python3
"""PostgreSQL backup script with compression, timestamps, and retention policy.

Usage:
    python scripts/backup.py [--output-dir ./backups] [--retention 7]

Requires:
    pg_dump on PATH (or via POSTGRES_BIN env var)
    gzip on PATH
"""

from __future__ import annotations

import argparse
import gzip
import logging
import os
import subprocess
import sys
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
logger = logging.getLogger("backup")


def _pg_dump_path() -> str:
    bin_dir = os.getenv("POSTGRES_BIN", "")
    return os.path.join(bin_dir, "pg_dump") if bin_dir else "pg_dump"


def _parse_db_url(url: str) -> dict[str, str]:
    """Rough parse of postgresql://user:pass@host:port/dbname."""
    # Strip protocol
    rest = url.replace("postgresql+asyncpg://", "postgresql://").replace("postgresql://", "")
    # user:pass
    creds, _, rest = rest.partition("@")
    user, _, password = creds.partition(":")
    # host:port/db
    host_port, _, db = rest.partition("/")
    host, _, port = host_port.partition(":")
    return {
        "user": user,
        "password": password,
        "host": host or "localhost",
        "port": port or "5432",
        "dbname": db.split("?")[0],
    }


def run_backup(output_dir: Path, retention_days: int) -> Path:
    """Run pg_dump, compress with gzip, and enforce retention policy.

    Returns the path to the created backup file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    db = _parse_db_url(settings.sync_database_url)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"borsa_backup_{timestamp}.sql.gz"
    out_path = output_dir / filename

    pg_dump = _pg_dump_path()
    cmd = [
        pg_dump,
        "--host", db["host"],
        "--port", db["port"],
        "--username", db["user"],
        "--dbname", db["dbname"],
        "--no-owner",
        "--no-privileges",
        "--clean",
        "--if-exists",
    ]

    env = os.environ.copy()
    env["PGPASSWORD"] = db["password"]

    logger.info("Starting backup: %s", out_path)
    try:
        with gzip.open(out_path, "wb", compresslevel=6) as gz:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )
            if proc.stdout:
                for chunk in iter(lambda: proc.stdout.read(1024 * 1024), b""):
                    gz.write(chunk)
            stderr = proc.stderr.read().decode() if proc.stderr else ""
            proc.wait()
            if proc.returncode != 0:
                raise RuntimeError(f"pg_dump failed (rc={proc.returncode}): {stderr}")
        logger.info("Backup complete: %s (%s bytes)", out_path, out_path.stat().st_size)
    except Exception:
        if out_path.exists():
            out_path.unlink()
        raise

    # Retention policy
    cutoff = datetime.utcnow() - timedelta(days=retention_days)
    removed = 0
    for f in sorted(output_dir.glob("borsa_backup_*.sql.gz")):
        try:
            # Extract timestamp from filename: borsa_backup_YYYYMMDD_HHMMSS.sql.gz
            ts_str = f.stem.replace("borsa_backup_", "").replace(".sql", "")
            ftime = datetime.strptime(ts_str, "%Y%m%d_%H%M%S")
            if ftime < cutoff:
                f.unlink()
                removed += 1
        except ValueError:
            continue

    if removed:
        logger.info("Retention cleanup removed %d old backup(s)", removed)

    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Borsa PostgreSQL Backup")
    parser.add_argument(
        "--output-dir",
        default=settings.backup_dir or "./backups",
        help="Directory to store backup files",
    )
    parser.add_argument(
        "--retention",
        type=int,
        default=settings.backup_retention_days or 7,
        help="Number of days to retain backups",
    )
    args = parser.parse_args()

    try:
        path = run_backup(Path(args.output_dir), args.retention)
        print(f"Backup created: {path}")
        return 0
    except Exception as exc:
        logger.error("Backup failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
