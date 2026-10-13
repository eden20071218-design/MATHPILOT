from datetime import date, timedelta
from uuid import UUID, uuid4
import pytest
from sqlalchemy import select, func
from app.main import app
from app.core.auth import require_admin, COOKIE, now
from app.models.auth import StudentAccount, LoginSession
from app.models.entities import Student, KnowledgePoint, KnowledgeDependency, Exam, Question, LearningTask, StudentKnowledgeState, TaskAttempt
from app.models.knowledge import KnowledgeRevision, MaterialSource
from app.models.planning import PlanningRun

HEADERS={'X-MathPilot-Request':'1'}
PASSWORD='Student-test-pass-2026'


@pytest.fixture
def web(client):
    app.dependency_overrides.pop(require_admin,None)
    client.headers.update(HEADERS)
    return client


def signup(web,email='one@example.test'):
    web.cookies.clear()
    response=web.post('/api/v1/auth/register',json={'email':email,'password':PASSWORD,'display_name':'测试同学'})
    assert response.status_code==201,response.text
    return response.json()


def configure(web):
    return web.put('/api/v1/student/settings',json={'display_name':'测试同学','target_score':80,'full_score':100,
        'target_date':(date.today()+timedelta(days=20)).isoformat(),'daily_minutes':60,'study_start':'19:00',
        'hide_scores':True,'reminders':{'timezone':'Asia/Shanghai','quiet_start':None,'quiet_end':None}})


def seed(db):
    a=KnowledgePoint(code='ST-FUNCTION',name='函数')
    b=KnowledgePoint(code='ST-DERIVATIVE',name='导数')
    db.add_all([a,b]);db.flush();db.add(KnowledgeDependency(prerequisite_id=a.id,dependent_id=b.id));db.commit()
    return a,b


def exam_payload(a,b,key='exam1'):
    return {'request_key':key,'title':'数学阶段测验','exam_date':date.today().isoformat(),'total_score':100,'achieved_score':50,
            'parts':[{'label':'综合题','score':50,'max_score':100,'difficulty':0.5,'knowledge_point_ids':[str(a.id),str(b.id)]}]}


def test_registration_cookie_password_and_logout(web,db):
    response=web.post('/api/v1/auth/register',json={'email':'NEW@example.test','password':PASSWORD,'display_name':'新同学'})
    assert response.status_code==201
    assert 'HttpOnly' in response.headers['set-cookie'] and 'SameSite=lax' in response.headers['set-cookie']
    account=db.scalar(select(StudentAccount))
    assert PASSWORD not in account.password_hash
    assert db.scalar(select(LoginSession)).token_hash!=web.cookies.get(COOKIE)
    assert web.get('/api/v1/auth/me').json()['email']=='new@example.test'
    saved=web.cookies.get(COOKIE)
    assert web.post('/api/v1/auth/logout').status_code==204
    web.cookies.set(COOKIE,saved)
    assert web.get('/api/v1/student/overview').status_code==401


def test_csrf_and_origin_reject(web):
    signup(web)
    assert web.post('/api/v1/auth/logout',headers={'X-MathPilot-Request':''}).status_code==403
    assert web.post('/api/v1/auth/logout',headers={'Origin':'https://evil.example'}).status_code==403
    assert web.get('/api/v1/auth/me').status_code==200


def test_login_lockout_expiry_and_revocation(web,db):
    user=signup(web)
    web.post('/api/v1/auth/logout')
    for _ in range(5):
        assert web.post('/api/v1/auth/login',json={'email':'one@example.test','password':'wrong-password'}).status_code==401
    assert web.post('/api/v1/auth/login',json={'email':'one@example.test','password':PASSWORD}).status_code==429
    account=db.scalar(select(StudentAccount));account.locked_until=now()-timedelta(seconds=1);db.commit()
    assert web.post('/api/v1/auth/login',json={'email':'one@example.test','password':PASSWORD}).status_code==200
    session=db.scalar(select(LoginSession).where(LoginSession.student_id==UUID(user['id'])));session.expires_at=now()-timedelta(seconds=1);db.commit()
    assert web.get('/api/v1/student/overview').status_code==401


def test_empty_workspace_and_no_secret_exposure(web):
    signup(web)
    response=web.get('/api/v1/student/overview')
    assert response.status_code==200 and response.headers['cache-control']=='no-store'
    body=response.json()
    assert body['tasks']==[] and body['exams']==[] and body['goal'] is None and body['diagnosis'] is None
    assert 'password_hash' not in response.text and 'token_hash' not in response.text
    assert web.post('/api/v1/student/planning',json={}).status_code==422


def test_admin_routes_closed_to_students_and_anonymous(web):
    for logged in (False,True):
        if logged: signup(web)
        for path in ['/students','/exams','/student-knowledge-states','/planning/runs/'+str(uuid4()),'/diagnoses/'+str(uuid4()),'/knowledge/points','/questions']:
            assert web.get('/api/v1'+path).status_code==403
        assert web.post('/api/v1/students',json={'email':'attack@example.test'}).status_code==403


def test_settings_validate_and_persist(web):
    signup(web)
    assert configure(web).status_code==200
    data=web.get('/api/v1/student/overview').json()
    assert data['goal']['target_score']==80 and data['preferences']['hide_scores']
    assert data['preferences']['study_start']=='19:00'
    assert web.put('/api/v1/student/settings',json={'student_id':str(uuid4())}).status_code==422


def test_exam_validation_and_idempotent_diagnosis(web,db):
    signup(web);a,b=seed(db)
    payload=exam_payload(a,b)
    bad={**payload,'achieved_score':51}
    assert web.post('/api/v1/student/exams',json=bad).status_code==422
    assert db.scalar(select(func.count()).select_from(Exam))==0
    response=web.post('/api/v1/student/exams',json=payload)
    assert response.status_code==201,response.text
    again=web.post('/api/v1/student/exams',json=payload)
    assert again.json()['duplicate'] and again.json()['exam_id']==response.json()['exam_id']
    assert db.scalar(select(func.count()).select_from(Question))==1
    overview=web.get('/api/v1/student/overview').json()
    points=overview['diagnosis']['report']['knowledge_points']
    assert sum(p['allocated_max_score'] for p in points)==100
    assert len(list(db.scalars(select(StudentKnowledgeState))))==2
    bad={**payload,'title':'不同内容'}
    assert web.post('/api/v1/student/exams',json=bad).status_code==409


def test_two_students_isolated_across_all_student_surfaces(web,db):
    first=signup(web);a,b=seed(db);configure(web)
    exam=web.post('/api/v1/student/exams',json=exam_payload(a,b)).json()
    plan=web.post('/api/v1/student/planning',json={})
    assert plan.status_code==200,plan.text
    task_id=plan.json()['tasks'][0]['id']
    second=signup(web,'two@example.test')
    overview=web.get('/api/v1/student/overview').json()
    assert overview['student']['id']==second['id']
    assert not overview['tasks'] and not overview['exams'] and overview['planning'] is None
    assert all(not k['history'] for k in overview['knowledge'])
    assert web.get('/api/v1/student/tasks/'+task_id).status_code==404
    assert web.get('/api/v1/student/exams/'+exam['exam_id']).status_code==404
    assert web.post('/api/v1/student/tasks/'+task_id+'/action',json={'action':'start'}).status_code==404
    assert web.post('/api/v1/reminders/tasks/'+task_id+'/feedback',json={'request_key':'attack','score_rate':1,'duration_minutes':20}).status_code==404
    assert web.post('/api/v1/reminders/tasks/'+task_id+'/schedule',json={'action':'cancel','reason':'attack'}).status_code==404
    assert first['id'] not in web.get('/api/v1/student/export').text
    assert web.get('/api/v1/reminders/inbox').json()==[]


def test_full_student_journey_reuses_graph_and_feedback(web,db):
    signup(web);a,b=seed(db);assert configure(web).status_code==200
    assert web.post('/api/v1/student/exams',json=exam_payload(a,b)).status_code==201
    response=web.post('/api/v1/student/planning',json={})
    assert response.status_code==200,response.text
    tasks=response.json()['tasks'];task_id=tasks[0]['id']
    detail=web.get('/api/v1/student/tasks/'+task_id).json()
    assert detail['task']['completion_criterion'] and detail['task']['scheduled_start'].endswith(('+00:00','Z'))
    assert web.post('/api/v1/student/tasks/'+task_id+'/action',json={'action':'lock'}).status_code==200
    assert web.post('/api/v1/student/tasks/'+task_id+'/action',json={'action':'start'}).status_code==200
    result=web.post('/api/v1/reminders/tasks/'+task_id+'/feedback',json={'request_key':'finished','score_rate':0.7,'duration_minutes':20})
    assert result.status_code==200,result.text
    assert web.get('/api/v1/student/tasks/'+task_id).json()['task']['status']=='completed'
    assert db.scalar(select(func.count()).select_from(TaskAttempt))==1
    assert web.post('/api/v1/student/tasks/'+task_id+'/action',json={'action':'start'}).status_code==409
    assert web.post('/api/v1/auth/logout-all').status_code==204
    assert web.get('/api/v1/student/overview').status_code==401


def test_disabled_student_and_forged_cookie(web,db):
    user=signup(web)
    student=db.get(Student,UUID(user['id']));student.is_active=False;db.commit()
    assert web.get('/api/v1/student/overview').status_code==401
    web.cookies.clear();web.cookies.set(COOKIE,'made-up-session')
    assert web.get('/api/v1/student/overview').status_code==401


def test_existing_student_cannot_be_claimed_by_public_signup(web,db):
    from app.account_admin import provision
    existing=Student(email='legacy@example.test',display_name='原有学生');db.add(existing);db.commit()
    response=web.post('/api/v1/auth/register',json={'email':existing.email,'password':PASSWORD,'display_name':'冒领'})
    assert response.status_code==409
    assert db.scalar(select(func.count()).select_from(StudentAccount))==0
    provision(db,existing.id,PASSWORD)
    with pytest.raises(ValueError,match='不会覆盖'): provision(db,existing.id,'Another-secret-123')
    assert web.post('/api/v1/auth/login',json={'email':existing.email,'password':PASSWORD}).status_code==200
    assert web.get('/api/v1/auth/me').json()['id']==str(existing.id)
