from celery import Celery
from app.core.config import settings

celery_app = Celery('mathpilot', broker=settings.redis_url, include=['app.jobs'])
celery_app.conf.update(
    timezone='UTC', enable_utc=True, task_ignore_result=True,
    task_serializer='json', accept_content=['json'], broker_connection_retry_on_startup=True,
    task_acks_late=True, task_reject_on_worker_lost=True, worker_prefetch_multiplier=1,
    beat_schedule={'database-outbox-every-15-seconds': {'task':'mathpilot.scan', 'schedule':15.0}},
)
