"""Notification service supporting email (SMTP), Slack (webhook), and dashboard channels.

All send methods are async.  Failed deliveries are captured in the DB audit log so
operators can retry or debug later.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_sessionmaker
from app.models.notification import NotificationLog

logger = logging.getLogger(__name__)


class NotificationService:
    """Central dispatcher for notifications across email, Slack, and dashboard."""

    def __init__(self) -> None:
        self._smtp: dict[str, Any] | None = None

    # ------------------------------------------------------------------
    # Low-level senders
    # ------------------------------------------------------------------

    async def send_email(
        self,
        *,
        to: str,
        subject: str,
        body: str,
        html: str | None = None,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
    ) -> dict[str, Any]:
        """Send an email via aiosmtplib (async SMTP).

        Returns a dict with ``status`` ("sent" | "failed") and optional ``error``.
        """
        if not settings.smtp_host:
            return {"status": "failed", "error": "SMTP host not configured"}

        try:
            import aiosmtplib
        except ImportError as exc:  # pragma: no cover
            return {"status": "failed", "error": f"aiosmtplib not installed: {exc}"}

        from email.message import EmailMessage

        msg = EmailMessage()
        msg["From"] = settings.smtp_user or "noreply@borsa.local"
        msg["To"] = to
        msg["Subject"] = subject
        if cc:
            msg["Cc"] = ", ".join(cc)
        if bcc:
            msg["Bcc"] = ", ".join(bcc)

        if html:
            msg.set_content(body)
            msg.add_alternative(html, subtype="html")
        else:
            msg.set_content(body)

        recipients = [to] + (cc or []) + (bcc or [])
        try:
            await aiosmtplib.send(
                msg,
                hostname=settings.smtp_host,
                port=settings.smtp_port or 587,
                username=settings.smtp_user,
                password=settings.smtp_password,
                start_tls=True,
            )
            logger.info("Email sent to %s — subject: %s", to, subject)
            return {"status": "sent"}
        except Exception as exc:
            logger.exception("Failed to send email to %s", to)
            return {"status": "failed", "error": str(exc)}

    async def send_slack(self, *, message: str, webhook_url: str | None = None) -> dict[str, Any]:
        """Post a plain-text message to a Slack incoming webhook.

        Returns a dict with ``status`` ("sent" | "failed") and optional ``error``.
        """
        url = webhook_url or settings.slack_webhook_url
        if not url:
            return {"status": "failed", "error": "Slack webhook URL not configured"}

        payload = {"text": message}
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
            logger.info("Slack message sent")
            return {"status": "sent"}
        except Exception as exc:
            logger.exception("Failed to send Slack message")
            return {"status": "failed", "error": str(exc)}

    async def send_dashboard(
        self,
        *,
        user_id: int,
        title: str,
        message: str,
        db: AsyncSession | None = None,
    ) -> dict[str, Any]:
        """Persist an in-app dashboard notification.

        For now this simply writes a ``NotificationLog`` row with channel="dashboard".
        A future frontend can poll or WebSocket-push these rows to users.
        """
        close_session = db is None
        if db is None:
            session_maker = get_sessionmaker()
            db = session_maker()

        try:
            log = NotificationLog(
                channel="dashboard",
                event_type="dashboard_alert",
                recipient=str(user_id),
                subject=title,
                body=message,
                status="sent",
                sent_at=datetime.utcnow(),
            )
            db.add(log)
            await db.commit()
            logger.info("Dashboard notification created for user %s", user_id)
            return {"status": "sent", "log_id": log.id}
        except Exception as exc:
            if db:
                await db.rollback()
            logger.exception("Failed to create dashboard notification")
            return {"status": "failed", "error": str(exc)}
        finally:
            if close_session and db:
                await db.close()

    # ------------------------------------------------------------------
    # High-level dispatcher
    # ------------------------------------------------------------------

    async def notify(
        self,
        event_type: str,
        data: dict[str, Any],
        channels: list[str] | None = None,
        db: AsyncSession | None = None,
    ) -> list[dict[str, Any]]:
        """Dispatch a notification to the requested channels and audit every attempt.

        Parameters
        ----------
        event_type:
            Logical event name, e.g. ``"pipeline_complete"``, ``"promotion"``,
            ``"backtest_failed"``.
        data:
            Payload dict.  Expected keys vary by channel:

            - *email*: ``to``, ``subject``, ``body``, optional ``html``
            - *slack*: ``message``, optional ``webhook_url``
            - *dashboard*: ``user_id``, ``title``, ``message``
        channels:
            List of channels to attempt.  Defaults to ``["email", "slack", "dashboard"]``.
        db:
            Optional existing async DB session.  If omitted a transient session is opened
            for audit logging.

        Returns
        -------
        List of result dicts, one per channel attempt.
        """
        channels = channels or ["email", "slack", "dashboard"]
        results: list[dict[str, Any]] = []

        close_session = db is None
        if db is None:
            session_maker = get_sessionmaker()
            db = session_maker()

        async def _audit(
            channel: str,
            result: dict[str, Any],
            recipient: str | None = None,
            subject: str | None = None,
            body: str | None = None,
        ) -> None:
            log = NotificationLog(
                channel=channel,
                event_type=event_type,
                recipient=recipient,
                subject=subject,
                body=body,
                status=result.get("status", "failed"),
                sent_at=datetime.utcnow() if result.get("status") == "sent" else None,
                error=result.get("error"),
            )
            db.add(log)

        try:
            if "email" in channels:
                email_result = await self.send_email(
                    to=data.get("to", ""),
                    subject=data.get("subject", ""),
                    body=data.get("body", ""),
                    html=data.get("html"),
                    cc=data.get("cc"),
                    bcc=data.get("bcc"),
                )
                await _audit(
                    "email",
                    email_result,
                    recipient=data.get("to"),
                    subject=data.get("subject"),
                    body=data.get("body"),
                )
                results.append({"channel": "email", **email_result})

            if "slack" in channels:
                slack_result = await self.send_slack(
                    message=data.get("message", ""),
                    webhook_url=data.get("webhook_url"),
                )
                await _audit(
                    "slack",
                    slack_result,
                    recipient=settings.slack_webhook_url,
                    subject=data.get("message", "")[:200],
                )
                results.append({"channel": "slack", **slack_result})

            if "dashboard" in channels:
                dash_result = await self.send_dashboard(
                    user_id=data.get("user_id", 0),
                    title=data.get("title", ""),
                    message=data.get("message", ""),
                    db=db,
                )
                # send_dashboard already commits; avoid double-audit by skipping _audit
                # when it succeeded inside its own transaction.
                if dash_result.get("status") != "sent":
                    await _audit(
                        "dashboard",
                        dash_result,
                        recipient=str(data.get("user_id", "")),
                        subject=data.get("title"),
                        body=data.get("message"),
                    )
                results.append({"channel": "dashboard", **dash_result})

            await db.commit()
        except Exception as exc:
            await db.rollback()
            logger.exception("Notification dispatch failed for event %s", event_type)
            results.append({"channel": "dispatch", "status": "failed", "error": str(exc)})
        finally:
            if close_session and db:
                await db.close()

        return results
