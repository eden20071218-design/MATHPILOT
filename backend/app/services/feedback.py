from datetime import timedelta
from uuid import UUID
from fastapi import HTTPException
from sqlalchemy import select, func
from app.models.entities import Student, LearningTask, LearningPlan, TaskAttempt, StudentKnowledgeState
from app.models.planning import PlanningRun
from app.models.reminders import FeedbackEvent
from app.schemas.planning import PlanningRequest
from app.services.diagnosis import ShrunkEvidenceModel
from app.services.knowledge_import import digest
from app.services.reminders import now_utc, sync_task, utc


def submit_feedback(db, student_id, task_id, data):
    # Same lock order as student scheduling/planning: student, then task.
    db.scalar(select(Student).where(Student.id == student_id).with_for_update())
    task = db.scalar(select(LearningTask).join(LearningPlan).where(LearningTask.id == task_id,
        LearningPlan.student_id == student_id).with_for_update())
    if task is None:
        raise HTTPException(404, '任务不存在')
    fingerprint = digest({'task_id': str(task_id), **data.model_dump(mode='json')})
    existing = db.scalar(select(FeedbackEvent).where(FeedbackEvent.student_id == student_id, FeedbackEvent.request_key == data.request_key))
    if existing:
        if existing.input_hash != fingerprint:
            raise HTTPException(409, '幂等键已用于不同反馈')
        return existing, True
    if task.status in ('completed', 'cancelled', 'skipped'):
        raise HTTPException(409, '任务已经结束，不能重复提交')
    at = now_utc()
    number = (db.scalar(select(func.max(TaskAttempt.attempt_number)).where(TaskAttempt.task_id == task.id)) or 0)+1
    attempt = TaskAttempt(task_id=task.id, attempt_number=number, started_at=at-timedelta(minutes=data.duration_minutes),
        completed_at=at, score=data.score_rate*100, feedback=data.notes,
        result_data={'score_rate':data.score_rate, 'difficulty': data.difficulty, 'duration_minutes':data.duration_minutes})
    db.add(attempt); db.flush()
    estimate = None
    low_count = 0
    if task.knowledge_point_id:
        # Recompute from distinct raw attempts; do not compound previously derived snapshots.
        observations = []
        records = db.scalars(select(TaskAttempt).join(LearningTask).join(LearningPlan).where(
            LearningPlan.student_id == student_id, LearningTask.knowledge_point_id == task.knowledge_point_id,
            TaskAttempt.completed_at.is_not(None)).order_by(TaskAttempt.completed_at.desc()).limit(100))
        rates = []
        for record in records:
            values = record.result_data or {}
            rate = values.get('score_rate')
            if not isinstance(rate, (float, int)) or not 0 <= rate <= 1:
                continue
            difficulty = values.get('difficulty', 0.5)
            if not isinstance(difficulty, (float, int)) or not 0 <= difficulty <= 1:
                difficulty = 0.5
            age = max(0, (at-utc(record.completed_at)).total_seconds()/86400)
            observations.append((rate, difficulty, 2**(-age/180)))
            rates.append(rate)
        estimate = ShrunkEvidenceModel().estimate(observations)
        low_count = sum(rate < 0.6 for rate in rates[:3])
    overdue = bool(task.due_at and utc(task.due_at)+timedelta(days=1) < at)
    reasons = []
    if low_count >= 2:
        reasons.append('最近三次练习中至少两次低于60%，需要调整练习安排')
    if overdue:
        reasons.append('任务完成较原定截止时间延迟超过一天，需要重新安排剩余任务')
    event = FeedbackEvent(student_id=student_id, task_id=task.id, attempt_id=attempt.id,
        request_key=data.request_key, input_hash=fingerprint,
        result={'estimate': estimate.model_dump(mode='json') if estimate else None, 'reasons':reasons,
                'model_scope':'task_attempts_only; 不与历史考试诊断的伪计数重复累加'},
        replan_status='pending' if reasons else 'not_needed')
    db.add(event); db.flush()
    if estimate:
        db.add(StudentKnowledgeState(student_id=student_id, knowledge_point_id=task.knowledge_point_id,
            mastery=estimate.index, confidence=estimate.confidence, evidence_count=len(observations),
            source_type='task_feedback', source_id=event.id, recorded_at=at))
    task.status = 'completed'
    sync_task(db, task, at)
    return event, False


def process_replan(db, event):
    from app.api.planning import save_run
    task = db.get(LearningTask, event.task_id)
    goal_id = db.get(LearningPlan, task.plan_id).goal_id
    latest = db.scalar(select(PlanningRun).join(LearningPlan).where(PlanningRun.student_id == event.student_id,
        LearningPlan.goal_id == goal_id, LearningPlan.status == 'active').order_by(LearningPlan.version.desc()))
    if latest is None:
        event.replan_status = 'needs_attention'; event.last_error = '无活动规划，无法自动重排'; db.commit(); return
    payload = dict(latest.request)
    payload.update(previous_run_id=str(latest.id), existing_tasks=[], reason=f'反馈事件{event.id}：'+'；'.join(event.result['reasons']))
    now = now_utc()
    original = PlanningRequest.model_validate(payload)
    if original.exam_at <= now:
        event.replan_status = 'needs_attention'; event.last_error = '考试期限已过'; db.commit(); return
    payload['start_at'] = max(original.start_at, now).isoformat()
    for k in payload['knowledge']:
        state = db.scalar(select(StudentKnowledgeState).where(StudentKnowledgeState.student_id == event.student_id,
            StudentKnowledgeState.knowledge_point_id == UUID(k['id'])).order_by(StudentKnowledgeState.recorded_at.desc()))
        if state:
            k['mastery'] = float(state.mastery)
            k['uncertainty'] = 1-float(state.confidence)
    try:
        # Planning request fingerprint makes event replay idempotent.
        frozen = event.result.get('replan_request')
        if frozen is None:
            event.result = {**event.result, 'replan_request':payload}
            db.commit()
        result = save_run(PlanningRequest.model_validate(frozen or payload), db)
        event.replan_status = 'completed'
        event.result = {**event.result, 'planning_run_id':str(result['id'])}
        event.last_error = None
    except (HTTPException, ValueError) as exc:
        db.rollback()
        event = db.get(FeedbackEvent, event.id)
        event.replan_status = 'needs_attention'
        event.last_error = str(getattr(exc, 'detail', str(exc)))[:2000]
    db.commit()
