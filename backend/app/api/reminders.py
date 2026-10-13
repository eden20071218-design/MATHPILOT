import secrets
from datetime import timedelta
from uuid import UUID
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.core.config import settings
from app.core.reminder_auth import authenticated_student
from app.models.entities import Student, LearningTask, LearningPlan, LearningGoal, Notification
from app.models.reminders import ReminderPreference, PushSubscription, Reminder, PushDelivery, FeedbackEvent
from app.schemas.reminders import ReminderSettings, SubscriptionInput, TaskChange, FeedbackInput, PushReceipt
from app.services.reminders import preference, sync_task, now_utc, utc, after_quiet
from app.services.knowledge_import import digest
from app.services.feedback import submit_feedback

router = APIRouter(prefix='/reminders', tags=['Reminders and feedback'])


def student_scope(student_id: UUID = Depends(authenticated_student), db: Session = Depends(get_db)):
    student = db.get(Student, student_id)
    if student is None or not student.is_active:
        raise HTTPException(404, '学生不存在')
    return student_id


@router.get('/public-key')
def public_key():
    if not settings.vapid_public_key:
        raise HTTPException(503, 'VAPID尚未配置')
    return {'public_key':settings.vapid_public_key}


@router.get('/settings', response_model=ReminderSettings)
def get_settings(student_id=Depends(student_scope), db: Session=Depends(get_db)):
    return preference(db, student_id)


@router.put('/settings', response_model=ReminderSettings)
def put_settings(data: ReminderSettings, student_id=Depends(student_scope), db: Session=Depends(get_db)):
    row = db.scalar(select(ReminderPreference).where(ReminderPreference.student_id == student_id))
    if row is None:
        row = ReminderPreference(student_id=student_id, settings=data.model_dump(mode='json')); db.add(row)
    else:
        row.settings = data.model_dump(mode='json')
    db.flush()
    for task in db.scalars(select(LearningTask).join(LearningPlan).where(LearningPlan.student_id == student_id)):
        sync_task(db, task, refresh_preferences=True)
    db.commit()
    return data


@router.post('/subscriptions')
def subscribe(data: SubscriptionInput, student_id=Depends(student_scope), db: Session=Depends(get_db)):
    fingerprint = digest(data.endpoint)
    row = db.scalar(select(PushSubscription).where(PushSubscription.endpoint_hash == fingerprint))
    if row and row.student_id != student_id:
        raise HTTPException(409, '该浏览器订阅已绑定其他学生，请先取消原订阅')
    if row is None:
        if len(list(db.scalars(select(PushSubscription).where(PushSubscription.student_id == student_id, PushSubscription.active.is_(True))))) >= 10:
            raise HTTPException(409, '最多保留10个活动浏览器订阅')
        row = PushSubscription(student_id=student_id, endpoint_hash=fingerprint, endpoint=data.endpoint, keys=data.keys)
        db.add(row)
    else:
        row.keys = data.keys; row.active=True
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback(); raise HTTPException(409, '订阅并发冲突，请重试') from exc
    return {'id':row.id, 'active':row.active}


@router.delete('/subscriptions/{subscription_id}', status_code=204)
def unsubscribe(subscription_id: UUID, student_id=Depends(student_scope), db: Session=Depends(get_db)):
    row = db.get(PushSubscription, subscription_id)
    if row is None or row.student_id != student_id:
        raise HTTPException(404, '订阅不存在')
    row.active=False; db.commit()
    return Response(status_code=204)


@router.post('/test')
def test_push(student_id=Depends(student_scope), db: Session=Depends(get_db)):
    at = now_utc()
    recent = db.scalar(select(Reminder).where(Reminder.student_id==student_id, Reminder.kind=='test', Reminder.created_at >= at-timedelta(minutes=1)))
    if recent:
        raise HTTPException(429, '请等待一分钟再发起测试')
    due = at+timedelta(seconds=60)
    row = Reminder(student_id=student_id, dedup_key='test-'+secrets.token_hex(24), kind='test', due_at=due,
        available_at=after_quiet(due, preference(db, student_id)))
    db.add(row); db.commit()
    return {'reminder_id':row.id, 'send_after':row.available_at, 'instruction':'关闭本网站全部标签页，保持浏览器和设备允许后台通知'}


@router.post('/receipts', status_code=204)
def receipt(data: PushReceipt, db: Session=Depends(get_db)):
    row = db.scalar(select(PushDelivery).where(PushDelivery.receipt_token == data.token))
    if row is None:
        raise HTTPException(404, '回执不存在')
    if row.displayed_at is None:
        row.displayed_at=now_utc(); row.open_windows=data.open_windows; row.status='displayed'
        db.commit()
    return Response(status_code=204)


@router.get('/deliveries')
def deliveries(student_id=Depends(student_scope), db: Session=Depends(get_db)):
    rows = db.execute(select(PushDelivery, Reminder).join(Reminder).where(Reminder.student_id == student_id)
        .order_by(PushDelivery.created_at.desc()).limit(100))
    return [{'id':d.id, 'reminder_id':r.id, 'kind':r.kind, 'task_id':r.task_id, 'status':d.status,
        'attempts':d.attempts, 'retries':max(0,d.attempts-1), 'last_error':d.last_error,
        'accepted_at':d.accepted_at, 'displayed_at':d.displayed_at, 'open_windows':d.open_windows} for d,r in rows]


@router.get('/inbox')
def inbox(student_id=Depends(student_scope), db: Session=Depends(get_db)):
    return list(db.scalars(select(Notification).where(Notification.student_id == student_id).order_by(Notification.created_at.desc()).limit(100)))


@router.post('/tasks/{task_id}/schedule')
def change_task(task_id: UUID, data: TaskChange, student_id=Depends(student_scope), db: Session=Depends(get_db)):
    # Serialize calendar changes with planning.save_run on the same student.
    db.scalar(select(Student).where(Student.id == student_id).with_for_update())
    task = db.scalar(select(LearningTask).join(LearningPlan).where(LearningTask.id==task_id, LearningPlan.student_id==student_id).with_for_update())
    if task is None:
        raise HTTPException(404, '任务不存在')
    if task.status in ('completed', 'in_progress', 'cancelled'):
        raise HTTPException(409, '已完成、进行中或已取消的任务不能改期')
    if data.action == 'cancel':
        task.status='cancelled'
    else:
        start, end = utc(data.start), utc(data.end)
        minutes = (end-start).total_seconds()/60
        if start < now_utc() or minutes != int(minutes) or minutes <= 0:
            raise HTTPException(422, '任务须在未来，时长须为正整数分钟')
        if data.action == 'postpone' and task.scheduled_start and start <= utc(task.scheduled_start):
            raise HTTPException(422, '延期开始时间必须晚于原时间')
        pref = preference(db, student_id); zone=ZoneInfo(pref.timezone)
        day = start.astimezone(zone).date()
        if day != end.astimezone(zone).date():
            raise HTTPException(422, '不支持跨当地日期任务')
        plan = db.get(LearningPlan, task.plan_id); goal=db.get(LearningGoal,plan.goal_id)
        if day > goal.target_date:
            raise HTTPException(422, '超过目标考试日期')
        used=0
        for other in db.scalars(select(LearningTask).join(LearningPlan).where(LearningPlan.student_id==student_id, LearningTask.id!=task.id)):
            if other.status in ('cancelled','skipped') or other.scheduled_start is None or other.due_at is None:
                continue
            a,b=utc(other.scheduled_start),utc(other.due_at)
            if a < end and b > start:
                raise HTTPException(409, '与已有任务时间冲突')
            if a.astimezone(zone).date() == day:
                used+=other.estimated_minutes
        if used+minutes > goal.daily_minutes:
            raise HTTPException(409, '超过每日学习时间上限')
        task.scheduled_start=start; task.due_at=end; task.estimated_minutes=int(minutes); task.status='scheduled'
    task.version+=1
    task.instructions=(task.instructions or '')+f'\n调整原因：{data.reason}'
    sync_task(db, task)
    db.commit()
    return task


@router.post('/tasks/{task_id}/feedback')
def feedback(task_id: UUID, data: FeedbackInput, student_id=Depends(student_scope), db: Session=Depends(get_db)):
    try:
        event, duplicate = submit_feedback(db, student_id, task_id, data)
        db.commit()
        return {'id':event.id, 'duplicate':duplicate, 'result':event.result, 'replan_status':event.replan_status}
    except IntegrityError as exc:
        db.rollback(); raise HTTPException(409, '反馈并发冲突，请重试') from exc


@router.get('/feedback/{event_id}')
def feedback_status(event_id: UUID, student_id=Depends(student_scope), db: Session=Depends(get_db)):
    event=db.get(FeedbackEvent,event_id)
    if event is None or event.student_id != student_id:
        raise HTTPException(404,'反馈不存在')
    return event
