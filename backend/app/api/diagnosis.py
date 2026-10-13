from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.diagnosis import DiagnosisRun
from app.models.entities import Exam, ExamQuestion, Question, QuestionKnowledgePoint, Student, StudentKnowledgeState
from app.schemas.diagnosis import DiagnosisRequest, DiagnosisReport, ExamResult, QuestionResult, Tag, StoredDiagnosisRequest
from app.services.diagnosis import diagnose
from app.services.knowledge_import import digest

router = APIRouter(prefix='/diagnoses', tags=['Mathematics diagnosis'])


@router.post('/preview', response_model=DiagnosisReport)
def preview(request: DiagnosisRequest):
    """Stateless diagnosis of submitted current and historical results."""
    return diagnose(request)


def load_exam(db: Session, exam: Exam, reasons=None) -> ExamResult:
    if exam.exam_date is None or exam.achieved_score is None:
        raise HTTPException(422, '考试缺少日期或总得分')
    rows = list(db.scalars(select(ExamQuestion).where(ExamQuestion.exam_id == exam.id).order_by(ExamQuestion.position)))
    if reasons and set(reasons) - {row.question_id for row in rows}:
        raise HTTPException(422, '失分原因引用了本次考试以外的题目')
    questions = []
    for row in rows:
        if row.student_score is None:
            raise HTTPException(422, '考试含未评分题目，不能将缺失成绩视为零分')
        question = db.get(Question, row.question_id)
        tags = db.scalars(select(QuestionKnowledgePoint).where(QuestionKnowledgePoint.question_id == question.id)
                          .order_by(QuestionKnowledgePoint.knowledge_point_id))
        questions.append(QuestionResult(question_id=question.id, score=row.student_score, max_score=row.max_score,
            difficulty=question.difficulty, tags=[Tag(knowledge_point_id=t.knowledge_point_id, weight=t.weight) for t in tags],
            reasons=(reasons or {}).get(question.id, [])))
    return ExamResult(exam_id=exam.id, exam_date=exam.exam_date, total_score=exam.achieved_score,
                      max_score=exam.total_score, questions=questions)


@router.post('/from-exam')
def from_exam(request: StoredDiagnosisRequest, db: Session = Depends(get_db)):
    if db.get(Student, request.student_id) is None:
        raise HTTPException(404, 'Student not found')
    exam = db.get(Exam, request.exam_id)
    if exam is None or exam.student_id != request.student_id:
        raise HTTPException(404, 'Student exam not found')
    if exam.status != 'completed':
        raise HTTPException(422, '仅诊断已完成考试')
    try:
        current = load_exam(db, exam, request.reasons)
        history_rows = list(db.scalars(select(Exam).where(Exam.student_id == request.student_id,
            Exam.status == 'completed', Exam.exam_date < exam.exam_date).order_by(Exam.exam_date, Exam.id)))
        # Existing Exam identifies revisions by title/version. Use only the latest
        # completed revision on a given sitting date, not every corrected copy.
        sittings = {}
        for historical in history_rows:
            key = (historical.title, historical.exam_date)
            if key not in sittings or historical.version > sittings[key].version:
                sittings[key] = historical
        history_rows = sorted(sittings.values(), key=lambda e: (e.exam_date, str(e.id)))
        if len(history_rows) > 100:
            raise HTTPException(422, '历史考试超过首版100次上限，请使用预览接口选择历史范围')
        data = DiagnosisRequest(student_id=request.student_id, current=current,
                                history=[load_exam(db, e) for e in history_rows])
    except ValidationError as exc:
        raise HTTPException(422, '成绩、题目标签或总分数据不一致：' + str(exc)) from exc
    report = diagnose(data)
    snapshot = data.model_dump(mode='json')
    fingerprint = digest(snapshot)
    existing = db.scalar(select(DiagnosisRun).where(DiagnosisRun.student_id == request.student_id,
        DiagnosisRun.input_hash == fingerprint, DiagnosisRun.model_version == report.model_version))
    if existing:
        return {'id': existing.id, 'duplicate': True, 'report': existing.report}
    run = DiagnosisRun(student_id=request.student_id, exam_id=exam.id, input_hash=fingerprint,
                       model_version=report.model_version, input_snapshot=snapshot, report=report.model_dump(mode='json'))
    try:
        db.add(run)
        db.flush()
        timestamp = datetime.now(timezone.utc)
        for performance in report.knowledge_points:
            db.add(StudentKnowledgeState(student_id=request.student_id,
                knowledge_point_id=performance.knowledge_point_id, mastery=performance.estimate.index,
                confidence=performance.estimate.confidence, evidence_count=sum(
                    any(t.knowledge_point_id == performance.knowledge_point_id for t in q.tags)
                    for e in [data.current, *data.history] for q in e.questions),
                source_type='diagnosis', source_id=run.id, recorded_at=timestamp))
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, '并发诊断冲突，已回滚；请重试') from exc
    return {'id': run.id, 'duplicate': False, 'report': run.report}


@router.get('/{run_id}')
def get_diagnosis(run_id: UUID, db: Session = Depends(get_db)):
    run = db.get(DiagnosisRun, run_id)
    if run is None:
        raise HTTPException(404, 'Diagnosis not found')
    return run
