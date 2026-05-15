from celery import Celery
from app.config import settings

celery_app = Celery(
    "borsa",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.tasks.pipeline_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    beat_schedule={
        "weekly-ingest": {
            "task": "app.tasks.pipeline_tasks.run_full_pipeline",
            "schedule": 604800,  # every week
        },
    },
)
