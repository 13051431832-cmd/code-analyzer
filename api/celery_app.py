# api/celery_app.py
from celery import Celery
from api.config import config

celery_app = Celery(
    "code_analyzer",
    broker=config.REDIS_URL,
    backend=config.REDIS_URL
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600 * 60,
    task_soft_time_limit=3200 * 60,
)

# 自动发现任务
celery_app.autodiscover_tasks(['api'])