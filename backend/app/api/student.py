"""Student-facing facade over existing diagnosis, planning and reminder services."""
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from uuid import UUID
from typing import Literal
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import Field, SecretStr, model_validator
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.core.auth import require_student, now
from app.db.session import get_db
from app.models.entities import Student, Exam, ExamQuestion, Question, QuestionKnowledgePoint, KnowledgePoint, KnowledgeDependency, StudentKnowledgeState, LearningGoal, LearningPlan, LearningTask, TaskAttempt
from app.models.auth import StudentAccount, ExamSubmission
from app.models.knowledge import KnowledgeRevision
from app.models.diagnosis import DiagnosisRun
from app.models.planning import PlanningRun
from app.schemas.knowledge import StrictModel
from app.schemas.diagnosis import StoredDiagnosisRequest
from app.schemas.planning import PlanningRequest
from app.schemas.reminders import ReminderSettings
from app.services.reminders import utc, sync_task, preference
from app.services.knowledge_import import digest
from app.api.diagnosis import from_exam
from app.api.planning import save_run_with_key
from app.api.reminders import put_settings

router=APIRouter(prefix='/student',tags=['Student workspace'])


def serial(row):
    if row is None: return None
    return jsonable_encoder({c.name:utc(getattr(row,c.name)) if isinstance(getattr(row,c.name),datetime) else getattr(row,c.name) for c in row.__table__.columns})


def catalog(db):
    # Only public catalog names/descriptions; never expose draft material or student questions.
    approved=select(KnowledgeRevision.knowledge_point_id).where(KnowledgeRevision.review_status=='approved')
    revised=select(KnowledgeRevision.knowledge_point_id)
    return list(db.scalars(select(KnowledgePoint).where((KnowledgePoint.id.in_(approved)) | (~KnowledgePoint.id.in_(revised))).order_by(KnowledgePoint.name).limit(200)))


def account_for(db, student):
    return db.scalar(select(StudentAccount).where(StudentAccount.student_id==student.id))


def goal_for(db, student):
    return db.scalar(select(LearningGoal).where(LearningGoal.student_id==student.id,LearningGoal.status=='active').order_by(LearningGoal.created_at.desc()))


def task_for(db, student, task_id, lock=False):
    statement=select(LearningTask).join(LearningPlan).where(LearningTask.id==task_id,LearningPlan.student_id==student.id)
    row=db.scalar(statement.with_for_update(of=LearningTask) if lock else statement)
    if row is None: raise HTTPException(404,'任务不存在')
    return row


def metadata_for(db,student):
    result={}
    for run in db.scalars(select(PlanningRun).join(LearningPlan).where(PlanningRun.student_id==student.id).order_by(LearningPlan.version.desc(),PlanningRun.created_at.desc())):
        for entry in run.result.get('tasks',[]): result.setdefault(entry['id'],entry)
    return result


def task_view(task,metadata):
    extra=metadata.get(str(task.id),{})
    return {**serial(task),'kind':extra.get('kind','learn'),'completion_criterion':extra.get('completion_criterion'),
            'difficulty':extra.get('difficulty'),'content':extra.get('content') or task.instructions}


@router.get('/overview')
def overview(student: Student=Depends(require_student),db: Session=Depends(get_db)):
    points=catalog(db); meta=metadata_for(db,student)
    rows=list(db.scalars(select(LearningTask).join(LearningPlan).where(LearningPlan.student_id==student.id).order_by(LearningTask.scheduled_start.desc()).limit(1000)))
    exams=list(db.scalars(select(Exam).where(Exam.student_id==student.id).order_by(Exam.exam_date.desc(),Exam.created_at.desc()).limit(100)))
    history={}
    for state in db.scalars(select(StudentKnowledgeState).where(StudentKnowledgeState.student_id==student.id).order_by(StudentKnowledgeState.recorded_at.desc()).limit(5000)):
        entries=history.setdefault(str(state.knowledge_point_id),[])
        if len(entries)<20: entries.append(serial(state))
    goal=goal_for(db,student)
    run=db.scalar(select(PlanningRun).join(LearningPlan).where(PlanningRun.student_id==student.id,LearningPlan.status=='active').order_by(PlanningRun.created_at.desc()))
    diagnosis=db.scalar(select(DiagnosisRun).where(DiagnosisRun.student_id==student.id).order_by(DiagnosisRun.created_at.desc()))
    account=account_for(db,student)
    return {'student':{'id':student.id,'display_name':student.display_name,'email':student.email,'timezone':student.timezone},
        'goal':serial(goal),'preferences':account.preferences if account else {},'reminders':preference(db,student.id),
        'knowledge':[{**serial(p),'history':history.get(str(p.id),[])} for p in points],
        'exams':[serial(e) for e in exams],'tasks':[task_view(t,meta) for t in rows],
        'planning':serial(run),'diagnosis':serial(diagnosis),
        'limits':{'exams':100,'tasks':1000,'knowledge':200,'history_per_point':20}}


class ExamPart(StrictModel):
    label: str=Field(min_length=1,max_length=200)
    score: Decimal=Field(ge=0,max_digits=8,decimal_places=2)
    max_score: Decimal=Field(gt=0,max_digits=8,decimal_places=2)
    difficulty: float=Field(default=0.5,ge=0,le=1,allow_inf_nan=False)
    knowledge_point_ids: list[UUID]=Field(default_factory=list,max_length=20)

    @model_validator(mode='after')
    def valid(self):
        if self.score>self.max_score or len(set(self.knowledge_point_ids))!=len(self.knowledge_point_ids):
            raise ValueError('得分不能超过满分，知识点标签不可重复')
        return self


class ExamInput(StrictModel):
    request_key: str=Field(min_length=1,max_length=100)
    title: str=Field(min_length=1,max_length=200)
    exam_date: date
    total_score: Decimal=Field(gt=0,max_digits=8,decimal_places=2)
    achieved_score: Decimal=Field(ge=0,max_digits=8,decimal_places=2)
    parts: list[ExamPart]=Field(min_length=1,max_length=200)

    @model_validator(mode='after')
    def totals(self):
        if sum(p.score for p in self.parts)!=self.achieved_score or sum(p.max_score for p in self.parts)!=self.total_score:
            raise ValueError('各题或独立得分项之和必须等于考试总分；多知识点题只录入一行')
        return self


@router.post('/exams',status_code=201)
def add_exam(data: ExamInput,student=Depends(require_student),db: Session=Depends(get_db)):
    db.scalar(select(Student).where(Student.id==student.id).with_for_update())
    if data.exam_date>now().astimezone(ZoneInfo(student.timezone)).date(): raise HTTPException(422,'不能录入未来考试成绩')
    fingerprint=digest(data.model_dump(mode='json'))
    prior=db.scalar(select(ExamSubmission).where(ExamSubmission.student_id==student.id,ExamSubmission.request_key==data.request_key))
    if prior:
        if prior.input_hash!=fingerprint: raise HTTPException(409,'此提交标识已用于其他成绩，请刷新后重试')
        return {'exam_id':prior.exam_id,'duplicate':True}
    allowed={p.id for p in catalog(db)}
    if any(not set(p.knowledge_point_ids)<=allowed for p in data.parts): raise HTTPException(422,'知识点不在可用目录中')
    version=(db.scalar(select(func.max(Exam.version)).where(Exam.student_id==student.id,Exam.title==data.title)) or 0)+1
    exam=Exam(student_id=student.id,title=data.title,exam_date=data.exam_date,total_score=data.total_score,achieved_score=data.achieved_score,status='completed',version=version)
    try:
        db.add(exam);db.flush()
        for i,part in enumerate(data.parts,1):
            question=Question(stem=part.label,difficulty=part.difficulty);db.add(question);db.flush()
            db.add(ExamQuestion(exam_id=exam.id,question_id=question.id,position=i,max_score=part.max_score,student_score=part.score))
            for key in part.knowledge_point_ids: db.add(QuestionKnowledgePoint(question_id=question.id,knowledge_point_id=key,weight=1))
        db.add(ExamSubmission(student_id=student.id,exam_id=exam.id,request_key=data.request_key,input_hash=fingerprint));db.flush()
        result=from_exam(StoredDiagnosisRequest(student_id=student.id,exam_id=exam.id),db)
        return {'exam_id':exam.id,'duplicate':False,'diagnosis_id':result['id']}
    except IntegrityError as exc:
        db.rollback();raise HTTPException(409,'成绩提交冲突，请重试') from exc


@router.get('/exams/{exam_id}')
def exam_detail(exam_id: UUID,student=Depends(require_student),db: Session=Depends(get_db)):
    exam=db.scalar(select(Exam).where(Exam.id==exam_id,Exam.student_id==student.id))
    if exam is None: raise HTTPException(404,'考试不存在')
    parts=[]
    for row in db.scalars(select(ExamQuestion).where(ExamQuestion.exam_id==exam.id).order_by(ExamQuestion.position)):
        question=db.get(Question,row.question_id)
        parts.append({**serial(row),'label':question.stem,'knowledge_point_ids':list(db.scalars(select(QuestionKnowledgePoint.knowledge_point_id).where(QuestionKnowledgePoint.question_id==row.question_id)))})
    return {'exam':serial(exam),'parts':parts}


@router.get('/tasks/{task_id}')
def task_detail(task_id: UUID,student=Depends(require_student),db: Session=Depends(get_db)):
    task=task_for(db,student,task_id)
    return {'task':task_view(task,metadata_for(db,student)),
        'attempts':[serial(r) for r in db.scalars(select(TaskAttempt).where(TaskAttempt.task_id==task.id).order_by(TaskAttempt.attempt_number.desc()))]}


class TaskAction(StrictModel):
    action: Literal['start','lock','unlock']


@router.post('/tasks/{task_id}/action')
def task_action(task_id: UUID,data: TaskAction,student=Depends(require_student),db: Session=Depends(get_db)):
    db.scalar(select(Student).where(Student.id==student.id).with_for_update())
    task=task_for(db,student,task_id,lock=True)
    if task.status in ('completed','cancelled','skipped'): raise HTTPException(409,'任务已经结束，不能修改')
    if data.action=='start': task.status='in_progress'
    else: task.is_locked=data.action=='lock'
    task.version+=1;sync_task(db,task);db.commit()
    return task_view(task,metadata_for(db,student))


class StudentSettings(StrictModel):
    display_name: str=Field(min_length=1,max_length=100)
    target_score: float=Field(ge=0,le=1000,allow_inf_nan=False)
    full_score: float=Field(default=100,gt=0,le=1000,allow_inf_nan=False)
    target_date: date
    daily_minutes: int=Field(ge=15,le=240)
    study_start: time=time(19,0)
    hide_scores: bool=False
    reminders: ReminderSettings

    @model_validator(mode='after')
    def valid(self):
        if self.target_score>self.full_score: raise ValueError('目标分数不能超过满分')
        if self.study_start.tzinfo or self.study_start.second or self.study_start.microsecond or self.study_start.hour*60+self.study_start.minute+self.daily_minutes>=1440:
            raise ValueError('学习时段须在同一天内，开始时间精确到分钟')
        today=now().astimezone(ZoneInfo(self.reminders.timezone)).date()
        if not today<=self.target_date<=today+timedelta(days=366): raise ValueError('考试日期须为今天至未来366天内')
        return self


@router.put('/settings')
def update_settings(data: StudentSettings,student=Depends(require_student),db: Session=Depends(get_db)):
    db.scalar(select(Student).where(Student.id==student.id).with_for_update())
    goal=goal_for(db,student)
    if goal is None:
        goal=LearningGoal(student_id=student.id,title='数学学习目标',target_date=data.target_date);db.add(goal)
    goal.target_score=data.target_score;goal.target_date=data.target_date;goal.daily_minutes=data.daily_minutes
    student.display_name=data.display_name;student.timezone=data.reminders.timezone
    account=account_for(db,student)
    account.preferences={'study_start':data.study_start.isoformat(timespec='minutes'),'full_score':data.full_score,'hide_scores':data.hide_scores}
    db.flush()
    put_settings(data.reminders,student.id,db)  # One transaction, including reminder reconciliation.
    return {'saved':True,'message':'设置已保存；学习时间或目标改变后，请到规划解释页重新生成计划'}


class GenerateInput(StrictModel):
    reason: str=Field(default='学生主动根据最新成绩和目标重新规划',min_length=1,max_length=1000)
    use_ai: bool=False
    deepseek_api_key: SecretStr | None=None

    @model_validator(mode='after')
    def key_requires_opt_in(self):
        if self.deepseek_api_key and not self.use_ai:
            raise ValueError('填写 DeepSeek API Key 时须明确开启 AI 建议')
        if self.use_ai and not self.deepseek_api_key:
            raise ValueError('开启 DeepSeek 建议时须提供自己的 API Key')
        if self.deepseek_api_key and not 8<=len(self.deepseek_api_key.get_secret_value().strip())<=512:
            raise ValueError('DeepSeek API Key 长度无效')
        return self


@router.post('/planning')
def generate(data: GenerateInput,student=Depends(require_student),db: Session=Depends(get_db)):
    db.scalar(select(Student).where(Student.id==student.id).with_for_update())
    goal=goal_for(db,student)
    if goal is None: raise HTTPException(422,'请先在设置中保存学习目标')
    exam=db.scalar(select(Exam).where(Exam.student_id==student.id,Exam.status=='completed').order_by(Exam.exam_date.desc(),Exam.created_at.desc()))
    if exam is None: raise HTTPException(422,'请先录入一次考试成绩，不能虚构当前成绩')
    points=catalog(db)
    if not points: raise HTTPException(422,'知识目录为空，请联系管理员导入并审核知识点')
    prefs=account_for(db,student).preferences
    zone=ZoneInfo(student.timezone);start=now();day=start.astimezone(zone).date();exam_at=datetime.combine(goal.target_date,time(23,59),zone)
    if exam_at<=start or (goal.target_date-day).days>366: raise HTTPException(422,'请更新有效的目标考试日期')
    windows=[]
    for offset in range((goal.target_date-day).days+1):
        a=datetime.combine(day+timedelta(days=offset),time.fromisoformat(prefs.get('study_start','19:00')),zone)
        b=a+timedelta(minutes=goal.daily_minutes)
        if a>=start and b<=exam_at: windows.append({'start':a,'end':b})
    if not windows: raise HTTPException(422,'考试前没有完整的可用学习时段，请调整目标或学习时间')
    states={}
    for state in db.scalars(select(StudentKnowledgeState).where(StudentKnowledgeState.student_id==student.id).order_by(StudentKnowledgeState.recorded_at.desc())): states.setdefault(state.knowledge_point_id,state)
    knowledge=[]
    for point in points:
        state=states.get(point.id)
        dependencies=list(db.scalars(select(KnowledgeDependency.prerequisite_id).where(KnowledgeDependency.dependent_id==point.id)))
        knowledge.append({'id':point.id,'name':point.name,'mastery':float(state.mastery) if state else 0.5,'uncertainty':1-float(state.confidence) if state else 1,
            'prerequisites':dependencies})
    previous=db.scalar(select(PlanningRun).join(LearningPlan).where(PlanningRun.student_id==student.id,LearningPlan.goal_id==goal.id,LearningPlan.status=='active').order_by(LearningPlan.version.desc()))
    full=float(prefs.get('full_score',100))
    request=PlanningRequest(student_id=student.id,goal_id=goal.id,previous_run_id=previous.id if previous else None,
        current_score=float(exam.achieved_score)/float(exam.total_score)*full,target_score=float(goal.target_score),full_score=full,
        start_at=start,exam_at=exam_at,timezone=student.timezone,daily_minutes=goal.daily_minutes,availability=windows,knowledge=knowledge,reason=data.reason,use_ai=data.use_ai)
    return save_run_with_key(request,db,ai_api_key=data.deepseek_api_key.get_secret_value().strip() if data.deepseek_api_key else None)


@router.get('/export')
def export(student=Depends(require_student),db: Session=Depends(get_db)):
    data=overview(student,db)
    data['exams']=[exam_detail(e.id,student,db) for e in db.scalars(select(Exam).where(Exam.student_id==student.id))]
    data['goals']=[serial(g) for g in db.scalars(select(LearningGoal).where(LearningGoal.student_id==student.id))]
    data['tasks']=[serial(t) for t in db.scalars(select(LearningTask).join(LearningPlan).where(LearningPlan.student_id==student.id))]
    data['knowledge_history']=[serial(s) for s in db.scalars(select(StudentKnowledgeState).where(StudentKnowledgeState.student_id==student.id))]
    data['planning_history']=[serial(r) for r in db.scalars(select(PlanningRun).where(PlanningRun.student_id==student.id))]
    data['diagnosis_history']=[serial(r) for r in db.scalars(select(DiagnosisRun).where(DiagnosisRun.student_id==student.id))]
    # Export excludes passwords, session tokens and Web Push endpoint credentials.
    data['attempts']=[serial(a) for a in db.scalars(select(TaskAttempt).join(LearningTask).join(LearningPlan).where(LearningPlan.student_id==student.id))]
    data['exported_at']=now().isoformat()
    return data
