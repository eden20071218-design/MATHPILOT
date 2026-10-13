import base64
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4
from types import SimpleNamespace
import pytest
from sqlalchemy import select, func
from app.main import app
from app.core.config import settings
from app.core.reminder_auth import authenticated_student, issue_token
from app.models.entities import Student, LearningGoal, LearningPlan, LearningTask, TaskAttempt, StudentKnowledgeState, KnowledgePoint, Notification
from app.models.reminders import Reminder, ReminderPreference, PushSubscription, PushDelivery, FeedbackEvent
from app.schemas.reminders import ReminderSettings
from app.services.reminders import after_quiet, sync_task, deliver, utc
from app.services.feedback import process_replan
from app import jobs

NOW=datetime(2026,10,14,4,0,tzinfo=timezone.utc)


@pytest.fixture
def setup(db, client, monkeypatch):
    student=Student(email='push@example.com',display_name='模拟学生')
    kp=KnowledgePoint(code='PUSH',name='函数')
    db.add_all([student,kp]); db.flush()
    goal=LearningGoal(student_id=student.id,title='Test',target_date=(NOW+timedelta(days=30)).date(),daily_minutes=90)
    db.add(goal); db.flush()
    plan=LearningPlan(student_id=student.id,goal_id=goal.id,name='Test',version=1,status='active')
    db.add(plan); db.flush()
    task=LearningTask(plan_id=plan.id,knowledge_point_id=kp.id,title='基础练习',sequence=1,
        scheduled_start=NOW+timedelta(minutes=10),due_at=NOW+timedelta(minutes=40),estimated_minutes=30,status='scheduled')
    db.add(task)
    db.add(ReminderPreference(student_id=student.id,settings=ReminderSettings(quiet_start=None,quiet_end=None).model_dump(mode='json')))
    db.commit()
    app.dependency_overrides[authenticated_student]=lambda:student.id
    monkeypatch.setattr('app.api.reminders.now_utc',lambda:NOW)
    monkeypatch.setattr('app.services.reminders.now_utc',lambda:NOW)
    monkeypatch.setattr('app.services.feedback.now_utc',lambda:NOW)
    yield student, task
    app.dependency_overrides.pop(authenticated_student,None)


def subscribe_db(db, student, suffix='1'):
    sub=PushSubscription(student_id=student.id,endpoint_hash=suffix*64,endpoint='https://fcm.googleapis.com/fcm/send/'+suffix,keys={})
    db.add(sub); db.commit(); return sub


def start_reminder(db, task):
    sync_task(db,task,NOW); db.commit()
    return db.scalar(select(Reminder).where(Reminder.task_id==task.id,Reminder.kind=='start'))


def test_timezone_overnight_quiet_and_dst():
    pref=ReminderSettings()
    at=datetime(2026,10,14,15,tzinfo=timezone.utc) # 23:00 Shanghai
    assert after_quiet(at,pref)==datetime(2026,10,15,0,tzinfo=timezone.utc)
    assert after_quiet(NOW,pref)==NOW
    us=ReminderSettings(timezone='America/New_York',quiet_start='22:00',quiet_end='08:00')
    assert after_quiet(datetime(2026,11,1,3,tzinfo=timezone.utc),us)==datetime(2026,11,1,13,tzinfo=timezone.utc)


def test_idempotent_scheduling_and_sending(db,setup):
    student,task=setup
    reminder=start_reminder(db,task)
    sync_task(db,task,NOW); db.commit()
    assert db.scalar(select(func.count()).select_from(Reminder))==2
    subscribe_db(db,student)
    calls=[]
    assert deliver(db,reminder.id,lambda s,p:calls.append(p),NOW)=='sent'
    assert deliver(db,reminder.id,lambda s,p:calls.append(p),NOW)=='not_claimed'
    assert len(calls)==1
    assert db.scalar(select(func.count()).select_from(Notification))==1


def test_changed_schedule_invalidates_old_queued_message(db,setup):
    student,task=setup
    old=start_reminder(db,task)
    task.scheduled_start+=timedelta(hours=1);task.due_at+=timedelta(hours=1)
    sync_task(db,task,NOW);db.commit()
    db.refresh(old);assert old.status=='cancelled'
    assert deliver(db,old.id,lambda *args:pytest.fail('旧提醒被发送'),NOW)=='not_claimed'
    assert len(list(db.scalars(select(Reminder).where(Reminder.status=='pending'))))==2


def test_completion_cancels_due_messages(db,setup):
    _,task=setup
    reminder=start_reminder(db,task)
    task.status='completed';db.commit()
    assert deliver(db,reminder.id,lambda *args:pytest.fail('已完成任务被提醒'),NOW)=='cancelled'


def test_overdue_only_when_due(db,setup):
    student,task=setup;subscribe_db(db,student)
    start_reminder(db,task)
    reminder=db.scalar(select(Reminder).where(Reminder.kind=='overdue'))
    assert deliver(db,reminder.id,lambda *args:pytest.fail('提前逾期提醒'),NOW)=='not_claimed'
    assert deliver(db,reminder.id,lambda *args:None,NOW+timedelta(minutes=41))=='sent'


def test_quiet_hours_defer_and_drop_stale_start(db,setup):
    student,task=setup
    row=db.scalar(select(ReminderPreference));row.settings=ReminderSettings(quiet_start='11:00',quiet_end='13:00').model_dump(mode='json')
    reminder=start_reminder(db,task)
    assert utc(reminder.available_at)==NOW+timedelta(hours=1)
    assert deliver(db,reminder.id,lambda *args:pytest.fail('过期开始提醒'),NOW+timedelta(hours=1))=='expired'


def test_retry_only_failed_device_and_record_attempts(db,setup):
    student,task=setup;reminder=start_reminder(db,task)
    a=subscribe_db(db,student,'1');b=subscribe_db(db,student,'2')
    calls=[]
    def sender(sub,payload):
        calls.append(sub.id)
        if sub.id==b.id:raise ConnectionError('secret endpoint should not leak')
    assert deliver(db,reminder.id,sender,NOW)=='pending'
    due=utc(reminder.available_at)
    assert due>NOW
    # A scan must not reset exponential backoff.
    sync_task(db,task,NOW);db.commit();assert utc(reminder.available_at)==due
    assert deliver(db,reminder.id,lambda sub,p:calls.append(sub.id),due)=='sent'
    assert calls.count(a.id)==1 and calls.count(b.id)==2
    rows=list(db.scalars(select(PushDelivery)))
    assert sorted(d.attempts for d in rows)==[1,2]


def test_expired_subscription_disabled(db,setup):
    student,task=setup;sub=subscribe_db(db,student);reminder=start_reminder(db,task)
    def failure(*args):
        exc=RuntimeError();exc.response=SimpleNamespace(status_code=410);raise exc
    assert deliver(db,reminder.id,failure,NOW)=='failed'
    db.refresh(sub);assert not sub.active
    delivery=db.scalar(select(PushDelivery));assert delivery.status=='expired'
    assert '410' in delivery.last_error


def test_preferences_disable_enable_and_lead(db,client,setup):
    _,task=setup;start_reminder(db,task)
    data={'enabled':False,'lead_minutes':5,'quiet_start':None,'quiet_end':None}
    assert client.put('/api/v1/reminders/settings',json=data).status_code==200
    assert not list(db.scalars(select(Reminder).where(Reminder.status=='pending')))
    data['enabled']=True
    assert client.put('/api/v1/reminders/settings',json=data).status_code==200
    pending=list(db.scalars(select(Reminder).where(Reminder.status=='pending')))
    assert len(pending)==2
    assert any(utc(r.due_at)==NOW+timedelta(minutes=5) for r in pending)


def test_display_receipt_without_open_windows(db,client,setup):
    student,task=setup;subscribe_db(db,student);reminder=start_reminder(db,task)
    deliver(db,reminder.id,lambda *args:None,NOW)
    row=db.scalar(select(PushDelivery))
    assert client.post('/api/v1/reminders/receipts',json={'token':row.receipt_token,'open_windows':0}).status_code==204
    db.refresh(row);assert row.status=='displayed' and row.open_windows==0
    assert client.get('/api/v1/reminders/deliveries').json()[0]['open_windows']==0


def test_feedback_idempotence_profile_and_no_single_failure_replan(db,client,setup):
    _,task=setup;start_reminder(db,task)
    data={'request_key':'feedback-1','score_rate':0.2,'duration_minutes':30}
    response=client.post(f'/api/v1/reminders/tasks/{task.id}/feedback',json=data)
    assert response.status_code==200,response.text
    assert response.json()['replan_status']=='not_needed'
    assert response.json()['result']['estimate']['index']!=0.2
    assert client.post(f'/api/v1/reminders/tasks/{task.id}/feedback',json=data).json()['duplicate']
    assert db.scalar(select(func.count()).select_from(TaskAttempt))==1
    assert db.scalar(select(func.count()).select_from(StudentKnowledgeState))==1
    data['score_rate']=0.9
    assert client.post(f'/api/v1/reminders/tasks/{task.id}/feedback',json=data).status_code==409
    assert not list(db.scalars(select(Reminder).where(Reminder.status=='pending')))


def test_repeated_low_feedback_triggers_durable_replan(db,client,setup):
    _,task=setup
    db.add(TaskAttempt(task_id=task.id,attempt_number=1,started_at=NOW-timedelta(days=1),completed_at=NOW-timedelta(hours=1),result_data={'score_rate':0.3}))
    db.commit()
    response=client.post(f'/api/v1/reminders/tasks/{task.id}/feedback',json={'request_key':'low','score_rate':0.2,'duration_minutes':20})
    assert response.json()['replan_status']=='pending'
    event=db.get(FeedbackEvent,UUID(response.json()['id']))
    process_replan(db,event)
    assert event.replan_status=='needs_attention' and '无活动规划' in event.last_error


def test_auth_and_ssrf_rejection(client,db,setup,monkeypatch):
    student,_=setup
    assert client.post('/api/v1/reminders/subscriptions',json={'endpoint':'http://127.0.0.1/private','keys':{}}).status_code==422
    app.dependency_overrides.pop(authenticated_student)
    monkeypatch.setattr(settings,'reminder_api_secret','x'*40)
    assert client.get('/api/v1/reminders/settings').status_code==401
    token=issue_token(student.id)
    assert client.get('/api/v1/reminders/settings',headers={'Authorization':'Bearer '+token}).status_code==200
    assert client.get('/api/v1/reminders/settings',headers={'Authorization':'Bearer '+issue_token(uuid4())}).status_code==404


def test_celery_scan_dispatches_outbox(db,setup,monkeypatch):
    from conftest import TestingSession
    _,task=setup;reminder=start_reminder(db,task)
    monkeypatch.setattr(jobs,'SessionLocal',TestingSession)
    monkeypatch.setattr(jobs,'now_utc',lambda:NOW)
    ids=[]
    monkeypatch.setattr(jobs.send_reminder,'delay',lambda key:ids.append(key))
    jobs.scan.run()
    assert str(reminder.id) in ids


def test_schedule_api_sync_and_ownership(db,client,setup):
    _,task=setup;start_reminder(db,task)
    response=client.post(f'/api/v1/reminders/tasks/{task.id}/schedule',json={'action':'postpone',
        'start':(NOW+timedelta(hours=1)).isoformat(),'end':(NOW+timedelta(hours=1,minutes=30)).isoformat(),'reason':'调整时间'})
    assert response.status_code==200,response.text
    assert len(list(db.scalars(select(Reminder).where(Reminder.status=='cancelled'))))==2
    assert client.post(f'/api/v1/reminders/tasks/{uuid4()}/schedule',json={'action':'cancel','reason':'取消'}).status_code==404
    assert client.post(f'/api/v1/reminders/tasks/{task.id}/schedule',json={'action':'cancel','reason':'无需学习'}).status_code==200


def test_zero_lead_survives_beat_delay(db,setup):
    student,task=setup;subscribe_db(db,student)
    db.scalar(select(ReminderPreference)).settings=ReminderSettings(lead_minutes=0,quiet_start=None,quiet_end=None).model_dump(mode='json')
    reminder=start_reminder(db,task)
    at=NOW+timedelta(minutes=10,seconds=15)
    sync_task(db,task,at);db.commit()
    assert deliver(db,reminder.id,lambda *args:None,at)=='sent'


def test_paused_plan_stops_and_resume_restores_reminders(db,client,setup):
    _,task=setup;start_reminder(db,task)
    assert client.patch(f'/api/v1/learning-plans/{task.plan_id}',json={'status':'paused'}).status_code==200
    assert not list(db.scalars(select(Reminder).where(Reminder.status=='pending')))
    assert client.patch(f'/api/v1/learning-plans/{task.plan_id}',json={'status':'active'}).status_code==200
    assert len(list(db.scalars(select(Reminder).where(Reminder.status=='pending'))))==2


def test_retry_limit_and_expired_lease(db,setup):
    student,task=setup;subscribe_db(db,student)
    start_reminder(db,task)
    reminder=db.scalar(select(Reminder).where(Reminder.kind=='overdue'))
    at=NOW+timedelta(minutes=41)
    reminder.status='processing';reminder.lease_until=at+timedelta(seconds=1);db.commit()
    assert deliver(db,reminder.id,lambda *a:pytest.fail('lease stolen'),at)=='not_claimed'
    def failure(*args):raise ConnectionError('private endpoint')
    at+=timedelta(seconds=2)
    for index in range(5):
        result=deliver(db,reminder.id,failure,at)
        assert result==('failed' if index==4 else 'pending')
        at=utc(reminder.available_at)
    row=db.scalar(select(PushDelivery))
    assert row.attempts==5 and row.last_error=='ConnectionError'


def test_subscription_api_idempotence_and_ownership(db,client,setup):
    student,_=setup
    encode=lambda b:base64.urlsafe_b64encode(b).decode().rstrip('=')
    payload={'endpoint':'https://fcm.googleapis.com/fcm/send/demo',
             'keys':{'p256dh':encode(b'\x04'+b'x'*64),'auth':encode(b'a'*16)}}
    first=client.post('/api/v1/reminders/subscriptions',json=payload)
    assert first.status_code==200,first.text
    assert client.post('/api/v1/reminders/subscriptions',json=payload).json()['id']==first.json()['id']
    other=Student(email='other@example.com',display_name='Other');db.add(other);db.commit()
    app.dependency_overrides[authenticated_student]=lambda:other.id
    assert client.post('/api/v1/reminders/subscriptions',json=payload).status_code==409
    assert client.delete('/api/v1/reminders/subscriptions/'+first.json()['id']).status_code==404
    app.dependency_overrides[authenticated_student]=lambda:student.id
    assert client.delete('/api/v1/reminders/subscriptions/'+first.json()['id']).status_code==204


def test_feedback_replans_real_graph_preserves_completed_and_reviews(db,client,monkeypatch):
    from examples.plan_learning import sample
    from app.api.planning import save_run
    from app.models.planning import PlanningRun
    request=sample()
    db.add(Student(id=request.student_id,email='graph-push@example.com',display_name='Demo'))
    db.add_all([KnowledgePoint(id=k.id,code=k.name,name=k.name) for k in request.knowledge]);db.flush()
    goal=LearningGoal(student_id=request.student_id,title='Demo',target_date=request.exam_at.date());db.add(goal);db.commit()
    request.goal_id=goal.id
    monkeypatch.setattr('app.services.reminders.now_utc',lambda:NOW)
    monkeypatch.setattr('app.services.feedback.now_utc',lambda:NOW)
    run=save_run(request,db)
    task=db.get(LearningTask,UUID(run['tasks'][0]['id']))
    db.add(TaskAttempt(task_id=task.id,attempt_number=1,started_at=NOW-timedelta(hours=1),completed_at=NOW-timedelta(minutes=30),result_data={'score_rate':0.2}));db.commit()
    app.dependency_overrides[authenticated_student]=lambda:request.student_id
    result=client.post(f'/api/v1/reminders/tasks/{task.id}/feedback',json={'request_key':'graph','score_rate':0.3,'duration_minutes':20}).json()
    event=db.get(FeedbackEvent,UUID(result['id']))
    assert event.replan_status=='pending'
    db.expire_all()  # The real Celery worker starts a fresh session after the API commits.
    process_replan(db,event)
    assert event.replan_status=='completed',event.last_error
    assert db.scalar(select(func.count()).select_from(PlanningRun))==2
    process_replan(db,event)
    assert db.scalar(select(func.count()).select_from(PlanningRun))==2
    db.refresh(task);assert task.status=='completed'
    assert not list(db.scalars(select(Reminder).where(Reminder.task_id==task.id,Reminder.status=='pending')))
    assert db.scalar(select(Reminder).where(Reminder.kind=='review',Reminder.status=='pending'))


def test_real_push_builds_encrypted_signed_request(monkeypatch):
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization
    from py_vapid import Vapid
    from app.services.reminders import real_push
    encode=lambda b:base64.urlsafe_b64encode(b).decode().rstrip('=')
    vapid=Vapid();vapid.generate_keys()
    private=vapid.private_key.private_bytes(serialization.Encoding.DER,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
    public=vapid.public_key.public_bytes(serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint)
    receiver=ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint)
    monkeypatch.setattr(settings,'vapid_private_key',encode(private))
    monkeypatch.setattr(settings,'vapid_public_key',encode(public))
    calls=[]
    def transport(self,*args,**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(status_code=201,headers={},text='')
    monkeypatch.setattr('requests.Session.request',transport)
    real_push(SimpleNamespace(endpoint='https://fcm.googleapis.com/fcm/send/test',keys={'p256dh':encode(receiver),'auth':encode(b'a'*16)}),{'body':'test'})
    assert calls and calls[0]['allow_redirects'] is False
    assert calls[0]['data']!=b'{"body": "test"}'
    assert any(key.lower()=='authorization' for key in calls[0]['headers'])


def test_cli_demo_is_idempotent(db,monkeypatch,capsys):
    import json
    from conftest import TestingSession
    from app.reminder_cli import seed_demo
    monkeypatch.setattr('app.db.session.SessionLocal',TestingSession)
    seed_demo();first=json.loads(capsys.readouterr().out)
    seed_demo();second=json.loads(capsys.readouterr().out)
    assert first==second
    assert db.scalar(select(func.count()).select_from(Student))==1
    assert db.scalar(select(func.count()).select_from(LearningTask))==1
    assert db.scalar(select(func.count()).select_from(Reminder))==2
