from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.notification import NotificationPreference

router = APIRouter(prefix="/notifications", tags=["notifications"])

PREFERENCE_NAME = "global"


class NotificationSettingsPayload(BaseModel):
    emailAlerts: bool = True
    slackWebhook: str = ""
    jobFailures: bool = True
    killSwitchTriggers: bool = True
    strategyPromotions: bool = False
    dailyDigest: bool = False


DEFAULT_SETTINGS = NotificationSettingsPayload().model_dump()


def _merge_settings(raw: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(DEFAULT_SETTINGS)
    if raw:
        for key, value in raw.items():
            if key in merged:
                merged[key] = value
    return merged


async def _get_preference(db: AsyncSession) -> NotificationPreference | None:
    result = await db.execute(
        select(NotificationPreference).where(NotificationPreference.name == PREFERENCE_NAME)
    )
    return result.scalar_one_or_none()


@router.get("/settings", response_model=NotificationSettingsPayload)
async def get_settings(db: AsyncSession = Depends(get_db)):
    pref = await _get_preference(db)
    return _merge_settings(pref.settings_json if pref else None)


@router.put("/settings", response_model=NotificationSettingsPayload)
async def update_settings(
    payload: NotificationSettingsPayload,
    db: AsyncSession = Depends(get_db),
):
    pref = await _get_preference(db)
    settings_json = payload.model_dump()
    if pref is None:
        pref = NotificationPreference(name=PREFERENCE_NAME, settings_json=settings_json)
        db.add(pref)
    else:
        pref.settings_json = settings_json
    await db.commit()
    return _merge_settings(pref.settings_json)
