"""
ArXiv Research Paper Scanner.

5A: Fetches recent quantitative finance papers from ArXiv API.
    Deduplicates via URL hash. Stores in arxiv_papers table.
    Endpoint: GET /research/papers

5B: Feature Extractor — sends abstracts to Claude API, extracts feature ideas.
    Stores in research_insights table.

5C: Auto-implementation pipeline (human-in-loop).
    Status flow: new → approved → implemented / rejected
    Implementation generates code via Claude API (requires human approval).

Scheduling: meant to run as a Celery task once per day.
"""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.arxiv_paper import ArxivPaper, ResearchInsight

logger = logging.getLogger(__name__)

# ArXiv categories to scan
ARXIV_CATEGORIES = [
    "q-fin.PM",   # Portfolio Management
    "q-fin.TR",   # Trading and Market Microstructure
    "q-fin.ST",   # Statistical Finance
    "q-fin.MF",   # Mathematical Finance
    "cs.LG",      # Machine Learning (for ML + finance papers)
]

MAX_PAPERS_PER_RUN = 50


# ---------------------------------------------------------------------------
# 5A: ArXiv Scanner
# ---------------------------------------------------------------------------

def _url_hash(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()


def _parse_arxiv_entry(entry: dict) -> dict | None:
    """Parse a single arxiv API entry into our schema."""
    try:
        arxiv_id = entry.get("id", "").split("/abs/")[-1].split("v")[0]
        url = entry.get("id", "")
        title = entry.get("title", "").replace("\n", " ").strip()
        abstract = entry.get("summary", "").replace("\n", " ").strip()
        authors = ", ".join(
            a.get("name", "") for a in (entry.get("author") or [])
            if isinstance(a, dict)
        )
        if isinstance(entry.get("author"), dict):
            authors = entry["author"].get("name", "")

        published_str = entry.get("published", "")
        try:
            published = datetime.fromisoformat(published_str.replace("Z", "+00:00"))
        except Exception:
            published = None

        categories = ""
        tags = entry.get("tag") or []
        if isinstance(tags, dict):
            tags = [tags]
        categories = ", ".join(t.get("term", "") for t in tags if isinstance(t, dict))

        return {
            "arxiv_id": arxiv_id,
            "url": url,
            "url_hash": _url_hash(url),
            "title": title[:500],
            "authors": authors[:1000] if authors else None,
            "abstract": abstract[:5000] if abstract else None,
            "published_date": published,
            "categories": categories[:200] if categories else None,
        }
    except Exception as exc:
        logger.debug("Error parsing arxiv entry: %s", exc)
        return None


class ArxivScanner:
    """
    Fetches and stores recent ArXiv papers.

    Usage:
        scanner = ArxivScanner(session)
        n = scanner.fetch_recent(days=7)
    """

    def __init__(self, session: Session):
        self.session = session

    def fetch_recent(self, days: int = 7, max_results: int = MAX_PAPERS_PER_RUN) -> int:
        """
        Fetch papers published in the last `days` days.

        Returns number of new papers stored.
        """
        try:
            import feedparser
        except ImportError:
            logger.error("feedparser not installed — run: pip install feedparser")
            return 0

        query = " OR ".join(f"cat:{cat}" for cat in ARXIV_CATEGORIES)
        url = (
            f"http://export.arxiv.org/api/query"
            f"?search_query={query}"
            f"&sortBy=submittedDate&sortOrder=descending"
            f"&max_results={max_results}"
        )

        try:
            feed = feedparser.parse(url)
        except Exception as exc:
            logger.error("ArXiv fetch failed: %s", exc)
            return 0

        new_count = 0
        for entry in feed.entries:
            parsed = _parse_arxiv_entry(vars(entry) if hasattr(entry, '__dict__') else entry)
            if parsed is None:
                continue

            # Deduplicate by URL hash
            existing = self.session.execute(
                select(ArxivPaper).where(ArxivPaper.url_hash == parsed["url_hash"])
            ).scalar_one_or_none()
            if existing:
                continue

            paper = ArxivPaper(**parsed)
            self.session.add(paper)
            new_count += 1

        try:
            self.session.commit()
        except Exception as exc:
            self.session.rollback()
            logger.error("ArXiv store failed: %s", exc)
            return 0

        logger.info("ArxivScanner: stored %d new papers", new_count)
        return new_count

    def get_recent(self, limit: int = 30, unread_only: bool = False) -> list[dict]:
        """Return recent papers as dicts."""
        q = select(ArxivPaper).order_by(ArxivPaper.published_date.desc()).limit(limit)
        if unread_only:
            q = q.where(ArxivPaper.is_read == False)  # noqa: E712
        rows = self.session.execute(q).scalars().all()
        return [
            {
                "id": r.id,
                "arxiv_id": r.arxiv_id,
                "url": r.url,
                "title": r.title,
                "authors": r.authors,
                "abstract": r.abstract,
                "published_date": r.published_date.isoformat() if r.published_date else None,
                "categories": r.categories,
                "is_read": r.is_read,
                "fetched_at": r.fetched_at.isoformat() if r.fetched_at else None,
            }
            for r in rows
        ]

    def mark_read(self, paper_id: int) -> bool:
        """Mark a paper as read."""
        paper = self.session.get(ArxivPaper, paper_id)
        if paper is None:
            return False
        paper.is_read = True
        self.session.commit()
        return True


# ---------------------------------------------------------------------------
# 5B: Feature Extractor (Claude API)
# ---------------------------------------------------------------------------

EXTRACTION_PROMPT = """You are a quantitative finance researcher.
Given this paper abstract, extract actionable trading features.

Abstract: {abstract}

Answer in JSON with exactly these fields:
{{
  "feature_name": "short_snake_case_name or null",
  "description": "one sentence explanation",
  "pseudocode": "3-5 line Python pseudo-code or null",
  "applicable": true or false
}}

Rules:
- Only mark applicable=true if it can be computed from: OHLCV data, financial statements, macro data, or news sentiment.
- pseudocode must use weekly_returns, close_prices, or financial_metrics as variable names.
- If not applicable, set feature_name and pseudocode to null."""


class FeatureExtractor:
    """
    Sends paper abstracts to Claude API and extracts feature ideas.

    Requires ANTHROPIC_API_KEY environment variable.

    Usage:
        extractor = FeatureExtractor(session)
        n = extractor.extract_from_unprocessed()
    """

    def __init__(self, session: Session, model: str = "claude-haiku-4-5-20251001"):
        self.session = session
        self.model = model

    def _call_claude(self, abstract: str) -> dict | None:
        """Call Claude API and parse JSON response."""
        import os
        import json
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            logger.warning("ANTHROPIC_API_KEY not set — skipping feature extraction")
            return None

        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            message = client.messages.create(
                model=self.model,
                max_tokens=512,
                messages=[{
                    "role": "user",
                    "content": EXTRACTION_PROMPT.format(abstract=abstract[:2000]),
                }],
            )
            raw = message.content[0].text.strip()
            # Extract JSON block
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            if match:
                return json.loads(match.group())
        except Exception as exc:
            logger.warning("Claude API call failed: %s", exc)
        return None

    def extract_from_paper(self, paper: ArxivPaper) -> ResearchInsight | None:
        """Extract feature insight from a single paper."""
        if not paper.abstract:
            return None

        parsed = self._call_claude(paper.abstract)
        if not parsed:
            return None

        insight = ResearchInsight(
            paper_id=paper.id,
            arxiv_id=paper.arxiv_id,
            feature_name=parsed.get("feature_name"),
            description=parsed.get("description"),
            pseudocode=parsed.get("pseudocode"),
            applicable=bool(parsed.get("applicable", False)),
            status="new",
        )
        self.session.add(insight)
        try:
            self.session.commit()
            return insight
        except Exception:
            self.session.rollback()
            return None

    def extract_from_unprocessed(self, limit: int = 10) -> int:
        """
        Process papers that don't yet have a research insight.

        Returns number of insights created.
        """
        # Find papers without insights
        processed_arxiv_ids = {
            r.arxiv_id for r in self.session.execute(select(ResearchInsight)).scalars().all()
            if r.arxiv_id
        }
        papers = self.session.execute(
            select(ArxivPaper)
            .where(ArxivPaper.abstract.isnot(None))
            .order_by(ArxivPaper.published_date.desc())
            .limit(limit * 3)  # fetch extra, filter below
        ).scalars().all()

        count = 0
        for paper in papers:
            if paper.arxiv_id in processed_arxiv_ids:
                continue
            if count >= limit:
                break
            insight = self.extract_from_paper(paper)
            if insight:
                count += 1

        logger.info("FeatureExtractor: created %d new insights", count)
        return count

    def get_insights(self, status: str | None = None, limit: int = 50) -> list[dict]:
        """Return research insights as dicts."""
        q = select(ResearchInsight).order_by(ResearchInsight.created_at.desc()).limit(limit)
        if status:
            q = q.where(ResearchInsight.status == status)
        rows = self.session.execute(q).scalars().all()
        return [
            {
                "id": r.id,
                "arxiv_id": r.arxiv_id,
                "feature_name": r.feature_name,
                "description": r.description,
                "pseudocode": r.pseudocode,
                "applicable": r.applicable,
                "status": r.status,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]

    def update_status(self, insight_id: int, status: str) -> bool:
        """Update insight status (new → approved / rejected / implemented)."""
        insight = self.session.get(ResearchInsight, insight_id)
        if insight is None:
            return False
        insight.status = status
        self.session.commit()
        return True


# ---------------------------------------------------------------------------
# 5C: Auto-implementation (human-in-loop)
# ---------------------------------------------------------------------------

IMPL_PROMPT = """You are a senior quantitative developer.
Implement this feature for a weekly stock prediction system.

Feature: {feature_name}
Description: {description}
Reference pseudocode:
{pseudocode}

Stack context:
- Input: daily close prices (pd.Series), weekly returns (pd.Series)
- Output: single float value (or np.nan if insufficient data)
- No lookahead bias — only use data available before prediction week
- Must handle NaN gracefully

Write a Python function named `compute_{safe_name}(close: pd.Series, weekly_returns: pd.Series) -> float`.
Return ONLY the function code, no explanation."""


class AutoImplementer:
    """
    Generates Python code for approved research insights via Claude API.

    ALWAYS requires human approval before merging. Status: approved → code_generated.

    Usage:
        impl = AutoImplementer(session)
        code = impl.generate_code(insight_id=5)
        # Human reviews code, then:
        impl.mark_implemented(insight_id=5, code=code)
    """

    def __init__(self, session: Session, model: str = "claude-sonnet-4-6"):
        self.session = session
        self.model = model

    def generate_code(self, insight_id: int) -> str | None:
        """
        Generate Python code for an approved insight.

        Returns generated code string, or None if generation failed.
        Does NOT automatically save or execute the code.
        """
        insight = self.session.get(ResearchInsight, insight_id)
        if insight is None or insight.status != "approved":
            logger.warning("AutoImplementer: insight %d not found or not approved", insight_id)
            return None

        import os
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            logger.warning("ANTHROPIC_API_KEY not set")
            return None

        safe_name = re.sub(r"[^a-z0-9_]", "_", (insight.feature_name or "feature").lower())

        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            message = client.messages.create(
                model=self.model,
                max_tokens=1024,
                messages=[{
                    "role": "user",
                    "content": IMPL_PROMPT.format(
                        feature_name=insight.feature_name or "unknown",
                        description=insight.description or "",
                        pseudocode=insight.pseudocode or "# no pseudocode provided",
                        safe_name=safe_name,
                    ),
                }],
            )
            code = message.content[0].text.strip()
            logger.info("AutoImplementer: generated code for insight %d (%d chars)", insight_id, len(code))
            return code
        except Exception as exc:
            logger.error("AutoImplementer: code generation failed: %s", exc)
            return None

    def sandbox_test(self, code: str) -> tuple[bool, str]:
        """
        Run generated code in a subprocess sandbox.

        Returns (passed, error_message).
        NEVER executes arbitrary code in the main process.
        """
        import subprocess
        import tempfile
        import os

        test_harness = f"""
import numpy as np
import pandas as pd

{code}

# Basic smoke test
close = pd.Series([100.0, 101.0, 99.5, 102.0, 103.0] * 20)
weekly_returns = pd.Series([0.01, -0.005, 0.025, 0.015] * 25)
result = list(locals().values())[-1](close, weekly_returns)
assert isinstance(result, (float, int)) or (isinstance(result, float) and np.isnan(result)), f"Bad return type: {{type(result)}}"
print("PASSED")
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(test_harness)
            tmp_path = f.name

        try:
            proc = subprocess.run(
                ["python", tmp_path],
                capture_output=True, text=True, timeout=10,
            )
            passed = proc.returncode == 0 and "PASSED" in proc.stdout
            error = proc.stderr.strip() if not passed else ""
            return passed, error
        except subprocess.TimeoutExpired:
            return False, "Timeout (10s)"
        except Exception as exc:
            return False, str(exc)
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    def mark_implemented(self, insight_id: int) -> bool:
        """Mark insight as implemented after human approval."""
        return FeatureExtractor(self.session).update_status(insight_id, "implemented")
