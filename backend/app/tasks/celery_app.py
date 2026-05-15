from types import SimpleNamespace

from celery import Celery
from celery.schedules import crontab
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
    timezone=settings.celery_timezone,
    enable_utc=True,
    task_track_started=True,
    task_publish_retry=False,
    broker_connection_timeout=2,
    beat_schedule={
        "weekly-full-pipeline": {
            "task": "app.tasks.pipeline_tasks.run_full_pipeline",
            "schedule": crontab(
                minute=settings.weekly_pipeline_minute,
                hour=settings.weekly_pipeline_hour,
                day_of_week=settings.weekly_pipeline_day_of_week,
            ),
        },
        "daily-paper-trade-evaluation": {
            "task": "app.tasks.pipeline_tasks.evaluate_paper_trades",
            "schedule": crontab(
                minute=settings.paper_eval_minute,
                hour=settings.paper_eval_hour,
                day_of_week=settings.paper_eval_day_of_week,
            ),
        },
    },
)


def enqueue_task(task, **kwargs):
    """Queue a Celery task with a deterministic no-broker path for tests."""
    if settings.environment.lower() == "test":
        return SimpleNamespace(id=f"test-{getattr(task, 'name', 'task')}")
    return task.apply_async(kwargs=kwargs, retry=False)
