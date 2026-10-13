"""Database-backed outbox: Celery scans due records, never depends on open pages."""
import json
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID
from zoneinfo import ZoneInfo
from sqlalchemy import select, update, or_
from sqlalchemy.orm import Session
from pywebpush import webpush, WebPushException
import requests
from app.core.config import settings
from app.models.entities import Student, LearningTask, LearningPlan, Notification
from app.models.planning import PlanningRun
from app.models.reminders import ReminderPreference, Reminder, PushSubscription, PushDelivery
from app.schemas.reminders import ReminderSettings, SubscriptionInput
from app.services.knowledge_import import digest

UTC = timezone.utc


def utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def now_utc():
    return datetime.now(UTC)


def preference(db, student_id):
    row = db.scalar(select(ReminderPreference).where(ReminderPreference.student_id == student_id))
    if row:
        return ReminderSettings.model_validate(row.settings)
    student = db.get(Student, student_id)
    return ReminderSettings(timezone=student.timezone if student else 'Asia/Shanghai')


def after_quiet(now, pref):
    if pref.quiet_start is None:
        return utc(now)
    zone = ZoneInfo(pref.timezone)
    local = utc(now).astimezone(zone)
    clock = local.time().replace(tzinfo=None)
    start, end = pref.quiet_start, pref.quiet_end
    quiet = start <= clock < end if start < end else clock >= start or clock < end
    if not quiet:
        return utc(now)
    day = local.date() + (timedelta(days=1) if start > end and clock >= start else timedelta())
    # Fold=1 chooses later instant in a fall-back overlap; UTC roundtrip handles DST gaps.
    return datetime.combine(day, end, tzinfo=zone).replace(fold=1).astimezone(UTC)


def task_kind(db, task_id):
    runs = db.scalars(select(PlanningRun).order_by(PlanningRun.created_at.desc()))
    for run in runs:
        entry = next((t for t in run.result.get('tasks', []) if t['id'] == str(task_id)), None)
        if entry:
            return entry.get('kind', 'learn')
    return 'learn'


def sync_task(db: Session, task: LearningTask, at=None, refresh_preferences=False):
    at = at or now_utc()
    plan = db.get(LearningPlan, task.plan_id)
    owner = plan.student_id
    pref = preference(db, owner)
    wanted = {}
    if pref.enabled and plan.status not in ('draft', 'paused', 'completed') and task.status not in ('completed', 'cancelled', 'skipped') and task.scheduled_start and task.due_at:
        kind = 'review' if task_kind(db, task.id) == 'review' else 'start'
        start = utc(task.scheduled_start)
        # Beat scans every 15s; allow a one-minute delivery grace for zero lead.
        if task.status != 'in_progress' and start+timedelta(minutes=1) >= at:
            due = start-timedelta(minutes=pref.lead_minutes)
            wanted[digest([str(task.id), kind, start.isoformat(), pref.lead_minutes])] = (kind, due)
        due = utc(task.due_at)
        wanted[digest([str(task.id), 'overdue', due.isoformat()])] = ('overdue', due)
    existing = list(db.scalars(select(Reminder).where(Reminder.task_id == task.id)))
    keys = {r.dedup_key: r for r in existing}
    for reminder in existing:
        if reminder.dedup_key not in wanted and reminder.status in ('pending', 'processing'):
            reminder.status = 'cancelled'
            notification = db.scalar(select(Notification).where(Notification.deduplication_key == reminder.dedup_key))
            if notification and notification.status == 'pending':
                notification.status = 'cancelled'
    for key, (kind, due) in wanted.items():
        if key not in keys:
            db.add(Reminder(student_id=owner, task_id=task.id, dedup_key=key, kind=kind,
                due_at=due, available_at=after_quiet(max(at, due), pref), status='pending'))
        elif keys[key].status == 'cancelled' or (refresh_preferences and keys[key].status == 'pending'):
            keys[key].status = 'pending'
            keys[key].available_at = after_quiet(max(at, due), pref)
    db.flush()


def sync_all(db):
    for task in db.scalars(select(LearningTask)):
        sync_task(db, task)


def real_push(subscription, payload):
    if not settings.vapid_private_key or not settings.vapid_public_key:
        raise ValueError('VAPID未配置')
    validated = SubscriptionInput(endpoint=subscription.endpoint, keys=subscription.keys)
    session = requests.Session()
    # Do not follow an endpoint redirect into a private/untrusted network.
    original = session.request
    session.request = lambda *args, **kwargs: original(*args, **{**kwargs, 'allow_redirects': False})
    try:
        response = webpush(subscription_info={'endpoint': validated.endpoint, 'keys': validated.keys},
            data=json.dumps(payload, ensure_ascii=False), vapid_private_key=settings.vapid_private_key,
            vapid_claims={'sub': settings.vapid_subject}, ttl=300, timeout=15, requests_session=session,
            headers={'Urgency': 'normal'})
        if response.status_code not in (200, 201, 202):
            raise ValueError('推送服务未接受消息')
    finally:
        session.close()


def deliver(db, reminder_id: UUID, sender=real_push, at=None):
    at = at or now_utc()
    claimed = db.execute(update(Reminder).where(Reminder.id == reminder_id,
        Reminder.available_at <= at,
        or_(Reminder.status == 'pending', (Reminder.status == 'processing') & (Reminder.lease_until <= at)))
        .values(status='processing', lease_until=at+timedelta(minutes=10)).execution_options(synchronize_session=False))
    db.commit()
    if not claimed.rowcount:
        return 'not_claimed'
    reminder = db.get(Reminder, reminder_id)
    db.refresh(reminder)
    db.scalar(select(Student).where(Student.id == reminder.student_id).with_for_update())
    pref = preference(db, reminder.student_id)
    if not pref.enabled:
        reminder.status = 'cancelled'; db.commit(); return 'cancelled'
    deferred = after_quiet(at, pref)
    if deferred > at:
        reminder.status = 'pending'; reminder.available_at = deferred; db.commit(); return 'quiet'
    task = None
    if reminder.task_id:
        task = db.scalar(select(LearningTask).where(LearningTask.id == reminder.task_id).with_for_update())
        if task is None or task.status in ('completed', 'cancelled', 'skipped') or not task.scheduled_start or not task.due_at:
            reminder.status = 'cancelled'; db.commit(); return 'cancelled'
        if db.get(LearningPlan, task.plan_id).status in ('draft', 'paused', 'completed'):
            reminder.status = 'cancelled'; db.commit(); return 'cancelled'
        if reminder.kind in ('start', 'review') and (task.status == 'in_progress' or utc(task.scheduled_start)+timedelta(minutes=1) < at):
            reminder.status = 'cancelled'; db.commit(); return 'expired'
        anchor = utc(task.due_at) if reminder.kind == 'overdue' else utc(task.scheduled_start)
        expected = digest([str(task.id), 'overdue', anchor.isoformat()]) if reminder.kind == 'overdue' else digest([str(task.id), reminder.kind, anchor.isoformat(), pref.lead_minutes])
        if expected != reminder.dedup_key:
            reminder.status = 'cancelled'; db.commit(); return 'stale'
    notification = db.scalar(select(Notification).where(Notification.deduplication_key == reminder.dedup_key))
    if notification is None:
        notification = Notification(student_id=reminder.student_id, task_id=reminder.task_id,
            deduplication_key=reminder.dedup_key, kind=reminder.kind, title='MathPilot 学习提醒',
            body={'start':'学习任务即将开始', 'review':'间隔复习即将开始', 'overdue':'学习任务已到期，请完成或调整计划', 'test':'关闭网页推送验收'}.get(reminder.kind, '学习提醒'),
            scheduled_at=reminder.due_at, channel='in_app', status='sent', sent_at=at)
        db.add(notification); db.flush()
    subscriptions = list(db.scalars(select(PushSubscription).where(PushSubscription.student_id == reminder.student_id, PushSubscription.active.is_(True))))
    retry, failed = False, False
    for subscription in subscriptions:
        delivery = db.scalar(select(PushDelivery).where(PushDelivery.reminder_id == reminder.id, PushDelivery.subscription_id == subscription.id))
        if delivery is None:
            delivery = PushDelivery(reminder_id=reminder.id, subscription_id=subscription.id,
                receipt_token=secrets.token_urlsafe(32), status='pending', attempts=0)
            db.add(delivery); db.flush()
        if delivery.status in ('accepted', 'displayed', 'expired', 'failed'):
            continue
        delivery.attempts += 1
        payload = {'title': notification.title, 'body': notification.body,
            'tag': 'mathpilot-'+reminder.dedup_key, 'url': '/', 'delivery_id': str(delivery.id),
            'receipt_url': settings.public_api_url+'/reminders/receipts', 'receipt_token': delivery.receipt_token}
        try:
            sender(subscription, payload)
            delivery.status = 'accepted'; delivery.accepted_at = at; delivery.last_error = None
        except Exception as exc:
            response = getattr(exc, 'response', None)
            code = getattr(response, 'status_code', None)
            # Never persist endpoint credentials or raw provider response bodies.
            delivery.last_error = f'{type(exc).__name__}: HTTP {code}' if code else type(exc).__name__
            if code in (404, 410):
                subscription.active = False; delivery.status = 'expired'; failed = True
            elif delivery.attempts >= 5 or (code is not None and 400 <= code < 500 and code != 429):
                delivery.status = 'failed'; failed = True
            else:
                retry = True
    failed = failed or any(d.status in ('failed', 'expired') for d in db.scalars(select(PushDelivery).where(PushDelivery.reminder_id == reminder.id)))
    if retry:
        maximum = max((d.attempts for d in db.scalars(select(PushDelivery).where(PushDelivery.reminder_id == reminder.id))), default=1)
        reminder.status = 'pending'; reminder.available_at = at+timedelta(seconds=min(3600, 30*2**maximum))
        reminder.last_error = '部分推送失败，等待重试'
    else:
        reminder.status = 'failed' if failed else ('sent' if subscriptions else 'in_app_only')
        reminder.last_error = '推送失败或订阅已失效' if failed else None
    reminder.lease_until = None
    db.commit()
    return reminder.status
