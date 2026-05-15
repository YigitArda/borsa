#!/usr/bin/env python3
"""Standalone CLI script to run the borsa smoke test suite.

Usage:
    python scripts/smoke_test.py [--base-url http://localhost:8000]

Exits with code 0 on pass, 1 on fail/warn.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

# Ensure backend is on sys.path when run standalone
ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.services.verification import SmokeTestRunner

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("smoke_test")


def _print_report(report) -> None:
    print("\n" + "=" * 60)
    print(f"SMOKE TEST REPORT — overall: {report.overall.upper()}")
    print("=" * 60)
    print(f"Started : {report.started_at.isoformat()}")
    print(f"Finished: {report.finished_at.isoformat()}")
    print(f"Duration: {(report.finished_at - report.started_at).total_seconds():.2f}s")
    print("-" * 60)

    for check in report.checks:
        icon = {"pass": "✓", "fail": "✗", "warn": "⚠", "skip": "⊘"}.get(check.status, "?")
        print(f"  {icon} {check.name:<25} {check.status.upper():<6} {check.message}")
        if check.details:
            detail_str = json.dumps(check.details, default=str)
            if len(detail_str) > 120:
                detail_str = detail_str[:117] + "..."
            print(f"       → {detail_str}")

    print("-" * 60)
    print(f"Summary: {report.summary}")
    print("=" * 60 + "\n")


async def main() -> int:
    parser = argparse.ArgumentParser(description="Borsa Smoke Test CLI")
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="Base URL for API endpoint checks (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON instead of human-readable report",
    )
    args = parser.parse_args()

    runner = SmokeTestRunner(base_url=args.base_url)
    report = await runner.run_full_smoke_test()

    if args.json:
        payload = {
            "overall": report.overall,
            "started_at": report.started_at.isoformat(),
            "finished_at": report.finished_at.isoformat(),
            "summary": report.summary,
            "checks": [
                {
                    "name": c.name,
                    "status": c.status,
                    "message": c.message,
                    "duration_ms": c.duration_ms,
                    "details": c.details,
                }
                for c in report.checks
            ],
        }
        print(json.dumps(payload, indent=2))
    else:
        _print_report(report)

    return 0 if report.overall == "pass" else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
