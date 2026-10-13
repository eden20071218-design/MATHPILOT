from datetime import timedelta
from uuid import UUID
from sqlalchemy import select, or_, update
from app.celery_app import celery_app
from app.db.session import SessionLocal
from app.models.reminders import Reminder, FeedbackEvent
from app.services.reminders import sync_all, deliver, now_utc
from app.services.feedback import process_replan


@celery_app.task(name='mathpilot.scan')
def scan():
    now = now_utc()
    with SessionLocal() as db:
        sync_all(db)
        db.commit()
        ids = db.scalars(select(Reminder.id).where(Reminder.available_at <= now,
            or_(Reminder.status == 'pending', (Reminder.status == 'processing') & (Reminder.lease_until <= now))).limit(500)).all()
        events = db.scalars(select(FeedbackEvent.id).where(or_(FeedbackEvent.replan_status == 'pending',
            (FeedbackEvent.replan_status == 'processing') & (FeedbackEvent.lease_until <= now))).limit(100)).all()
    for key in ids:
        send_reminder.delay(str(key))
    for key in events:
        replan_feedback.delay(str(key))


@celery_app.task(name='mathpilot.send_reminder', autoretry_for=(ConnectionError,), retry_backoff=True, max_retries=3)
def send_reminder(reminder_id):
    with SessionLocal() as db:
        return deliver(db, UUID(reminder_id))


@celery_app.task(name='mathpilot.replan_feedback')
def replan_feedback(event_id):
    now = now_utc()
    with SessionLocal() as db:
        claim = db.execute(update(FeedbackEvent).where(FeedbackEvent.id == UUID(event_id),
            or_(FeedbackEvent.replan_status == 'pending', (FeedbackEvent.replan_status == 'processing') & (FeedbackEvent.lease_until <= now)))
            .values(replan_status='processing', lease_until=now+timedelta(minutes=10), attempts=FeedbackEvent.attempts+1).execution_options(synchronize_session=False))
        db.commit()
        if not claim.rowcount:
            return
        event = db.get(FeedbackEvent, UUID(event_id))
        if event.attempts > 5:
            event.replan_status='needs_attention'; event.last_error='自动重排超过重试上限'; db.commit(); return
        process_replan(db, event)
