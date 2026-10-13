from datetime import timezone
from uuid import UUID
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.entities import Student, KnowledgePoint, KnowledgeDependency, LearningGoal, LearningPlan, LearningTask, TaskAttempt
from app.models.planning import PlanningRun
from app.schemas.planning import PlanningRequest, PlannedTask
from app.services.planning import build_workflow, plan, protected, PlanningConflict
from app.services.knowledge_import import digest

router = APIRouter(prefix='/planning', tags=['Personalized planning'])


@router.post('/preview')
def preview(request: PlanningRequest):
    try:
        return plan(request)
    except PlanningConflict as exc:
        raise HTTPException(409, str(exc)) from exc


def aware(value):
    # SQLite strips timezone offsets; persistence below stores UTC instants.
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


@router.post('/runs')
def save_run(request: PlanningRequest, db: Session = Depends(get_db)):
    if db.scalar(select(Student).where(Student.id == request.student_id).with_for_update()) is None:
        raise HTTPException(404, '学生不存在')
    goal = db.get(LearningGoal, request.goal_id) if request.goal_id else None
    if goal is None or goal.student_id != request.student_id:
        raise HTTPException(422, '保存规划须提供属于该学生的 goal_id')
    for k in request.knowledge:
        if db.get(KnowledgePoint, k.id) is None:
            raise HTTPException(422, '知识点不存在，请先导入知识库')
    previous = db.get(PlanningRun, request.previous_run_id) if request.previous_run_id else None
    if request.previous_run_id and (previous is None or previous.student_id != request.student_id):
        raise HTTPException(404, '原规划不存在或不属于该学生')
    if previous and db.get(LearningPlan, previous.plan_id).goal_id != goal.id:
        raise HTTPException(409, '重新规划必须属于同一学习目标')
    # Persisted task status is authoritative. Do not let callers erase locked tasks.
    if request.existing_tasks:
        raise HTTPException(422, '保存接口从数据库读取已有任务；existing_tasks仅用于预览')
    fingerprint = digest({'request': request.model_dump(mode='json'), 'model': 'planner-v1'})
    duplicate = db.scalar(select(PlanningRun).where(PlanningRun.student_id == request.student_id, PlanningRun.fingerprint == fingerprint))
    if duplicate:
        return {'id': duplicate.id, 'plan_id': duplicate.plan_id, 'duplicate': True, **duplicate.result}
    previous_ids = {UUID(t['id']) for t in previous.result['tasks']} if previous else set()
    metadata = {UUID(t['id']): t for t in previous.result['tasks']} if previous else {}
    existing = []
    rows = list(db.scalars(select(LearningTask).join(LearningPlan).where(LearningPlan.student_id == request.student_id)))
    for row in rows:
        active = row.status not in ('cancelled', 'skipped', 'completed')
        retain = row.id in previous_ids and (row.status in ('completed', 'in_progress') or row.is_locked)
        other = row.id not in previous_ids and active
        if not retain and not other:
            continue
        if row.scheduled_start is None or row.due_at is None or row.knowledge_point_id is None:
            raise HTTPException(409, '已有任务缺少时间或知识点，无法验证冲突')
        if other and aware(row.due_at) <= request.start_at:
            continue
        task = PlannedTask(id=row.id, knowledge_point_id=row.knowledge_point_id,
            kind=metadata.get(row.id, {}).get('kind', 'learn'), content=row.instructions or row.title,
            minutes=row.estimated_minutes, difficulty=metadata.get(row.id, {}).get('difficulty', 0.5),
            completion_criterion=metadata.get(row.id, {}).get('completion_criterion', '按原任务要求完成'),
            start=aware(row.scheduled_start), end=aware(row.due_at), status=row.status.value,
            locked=row.is_locked or other)
        existing.append(task)
    knowledge = [k.model_copy(deep=True) for k in request.knowledge]
    by_id = {k.id: k for k in knowledge}
    for dependency in db.scalars(select(KnowledgeDependency).where(KnowledgeDependency.dependent_id.in_(by_id))):
        if dependency.prerequisite_id not in by_id:
            raise HTTPException(422, '请求遗漏数据库中必要的前置知识点')
        k = by_id[dependency.dependent_id]
        if dependency.prerequisite_id not in k.prerequisites:
            k.prerequisites.append(dependency.prerequisite_id)
    updates = {'existing_tasks': existing, 'knowledge': knowledge}
    prior_rows = [row for row in rows if row.id in previous_ids and row.status in ('completed', 'skipped')]
    if prior_rows:
        updates['completion_rate'] = sum(row.status == 'completed' for row in prior_rows)/len(prior_rows)
    for attempt, task in db.execute(select(TaskAttempt, LearningTask).join(LearningTask, TaskAttempt.task_id == LearningTask.id)
        .join(LearningPlan, LearningTask.plan_id == LearningPlan.id).where(LearningPlan.student_id == request.student_id,
            TaskAttempt.completed_at <= request.start_at)
        .order_by(TaskAttempt.started_at, TaskAttempt.id)):
        rate = (attempt.result_data or {}).get('score_rate')
        if task.knowledge_point_id in by_id and isinstance(rate, (float, int)) and 0 <= rate <= 1:
            k = by_id[task.knowledge_point_id]
            k.practice_rates = (k.practice_rates + [rate])[-100:]
    effective = request.model_copy(update=updates)
    if previous and db.get(LearningPlan, previous.plan_id).status == 'superseded':
        raise HTTPException(409, '该规划已有后续版本，请使用最新规划')

    def persist(state):
        goal.target_score = request.target_score
        goal.target_date = request.exam_at.astimezone(ZoneInfo(request.timezone)).date()
        goal.daily_minutes = request.daily_minutes
        version = (db.scalar(select(func.max(LearningPlan.version)).where(LearningPlan.goal_id == goal.id)) or 0)+1
        learning_plan = LearningPlan(student_id=request.student_id, goal_id=goal.id, name='个性化数学学习计划',
            version=version, status='active', rationale='；'.join(state['result']['adjustment_reasons']))
        db.add(learning_plan); db.flush()
        kept = {t.id for t in existing}
        for sequence, task in enumerate(state['tasks'], 1):
            if task.id in kept:
                continue
            db.add(LearningTask(id=task.id, plan_id=learning_plan.id, knowledge_point_id=task.knowledge_point_id,
                title=task.content[:200], instructions=task.content, sequence=sequence, version=1,
                status='scheduled', scheduled_start=task.start.astimezone(timezone.utc), due_at=task.end.astimezone(timezone.utc),
                estimated_minutes=task.minutes, is_locked=task.locked))
        if previous:
            db.get(LearningPlan, previous.plan_id).status = 'superseded'
            for row in rows:
                if row.id in previous_ids and row.id not in kept and row.status not in ('completed', 'in_progress'):
                    row.status = 'cancelled'
        run = PlanningRun(student_id=request.student_id, plan_id=learning_plan.id, previous_run_id=request.previous_run_id,
            fingerprint=fingerprint, request=effective.model_dump(mode='json'), result=state['result'])
        db.add(run); db.flush()
        from app.services.reminders import sync_task
        for task in db.scalars(select(LearningTask).join(LearningPlan).where(LearningPlan.student_id == request.student_id)):
            sync_task(db, task)
        return {'result': {'id': str(run.id), 'plan_id': str(learning_plan.id), 'duplicate': False, **state['result']}}
    try:
        result = build_workflow(persist).invoke({'request': effective})['result']
        db.commit()
        return result
    except (PlanningConflict, IntegrityError) as exc:
        db.rollback()
        raise HTTPException(409, str(exc) if isinstance(exc, PlanningConflict) else '并发规划冲突，已回滚，请重试') from exc


@router.get('/runs/{run_id}')
def get_run(run_id: UUID, db: Session = Depends(get_db)):
    run = db.get(PlanningRun, run_id)
    if run is None:
        raise HTTPException(404, '规划不存在')
    return run
