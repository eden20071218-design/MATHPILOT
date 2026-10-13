from datetime import date
from uuid import UUID, uuid4
import pytest
from sqlalchemy import func, select
from app.models.entities import Student, Exam, ExamQuestion, KnowledgePoint, Question, QuestionKnowledgePoint, StudentKnowledgeState
from app.models.diagnosis import DiagnosisRun
from app.schemas.diagnosis import DiagnosisRequest
from app.services.diagnosis import diagnose, ShrunkEvidenceModel
from examples.diagnose_exam import sample


def test_single_perfect_score_is_not_mastery_probability():
    estimate = ShrunkEvidenceModel().estimate([(1, 0.5, 1)])
    assert estimate.index == pytest.approx(0.6)
    assert estimate.confidence == pytest.approx(0.2)
    assert estimate.interval_95[0] < estimate.index < estimate.interval_95[1]


def test_fractional_allocation_conserves_score_and_evidence():
    payload = sample().model_dump(mode='json')
    payload['history'] = []
    payload['current']['questions'][0]['tags'].append({'knowledge_point_id': str(UUID(int=3)), 'weight': 3})
    report = diagnose(DiagnosisRequest.model_validate(payload))
    assert sum(k.allocated_score for k in report.knowledge_points) == pytest.approx(8)
    assert sum(k.allocated_lost_score for k in report.knowledge_points) == pytest.approx(12)
    assert sum(k.estimate.evidence_strength for k in report.knowledge_points) == pytest.approx(1)
    assert report.knowledge_points[0].allocated_score == pytest.approx(2)


def test_persistent_weakness_and_reason_accounting():
    report = diagnose(sample())
    assert report.knowledge_points[0].persistent_weakness
    assert report.loss_by_reason['unknown'] == 4
    assert sum(report.loss_by_reason.values()) == 12
    payload = sample().model_dump(mode='json')
    payload['history'] = []
    assert not diagnose(DiagnosisRequest.model_validate(payload)).knowledge_points[0].persistent_weakness


def test_history_decay_and_difficulty_direction():
    model = ShrunkEvidenceModel()
    assert model.estimate([(1, 0.9, 1)]).index > model.estimate([(1, 0.1, 1)]).index
    assert model.estimate([(0, 0.9, 1)]).index > model.estimate([(0, 0.1, 1)]).index
    data = sample().model_dump(mode='json')
    original = diagnose(DiagnosisRequest.model_validate(data))
    data['history'][0]['exam_date'] = '2020-01-01'
    older = diagnose(DiagnosisRequest.model_validate(data))
    assert older.knowledge_points[0].estimate.evidence_strength < original.knowledge_points[0].estimate.evidence_strength
    assert not older.knowledge_points[0].persistent_weakness


@pytest.mark.parametrize('change', ['score', 'duplicate', 'future', 'weight', 'reason'])
def test_invalid_inputs_rejected(client, change):
    data = sample().model_dump(mode='json')
    question = data['current']['questions'][0]
    if change == 'score': data['current']['total_score'] = 100
    if change == 'duplicate': data['history'].append(data['history'][0])
    if change == 'future': data['history'][0]['exam_date'] = '2027-01-01'
    if change == 'weight': question['tags'][0]['weight'] = 0
    if change == 'reason': question['reasons'][0]['lost_score'] = 100
    assert client.post('/api/v1/diagnoses/preview', json=data).status_code == 422


def test_missing_tags_and_reasons_stay_unknown(client):
    data = sample().model_dump(mode='json')
    data['history'] = []
    data['current']['questions'][0]['tags'] = []
    data['current']['questions'][0]['reasons'] = []
    report = client.post('/api/v1/diagnoses/preview', json=data).json()
    assert report['untagged_lost_score'] == report['loss_by_reason']['unknown'] == 12
    assert report['knowledge_points'] == []


def test_persist_idempotent_history_snapshots(client, db):
    student = Student(email='diagnosis@example.com', display_name='Example')
    kp = KnowledgePoint(code='DIAG', name='导数')
    question = Question(stem='Example', difficulty=0.5)
    db.add_all([student, kp, question]); db.flush()
    exam = Exam(student_id=student.id, title='Example', exam_date=date(2026,10,13), total_score=20,
                achieved_score=8, status='completed')
    db.add(exam); db.flush()
    db.add_all([ExamQuestion(exam_id=exam.id, question_id=question.id, position=1, max_score=20, student_score=8),
                QuestionKnowledgePoint(question_id=question.id, knowledge_point_id=kp.id, weight=1)])
    db.commit()
    request = {'student_id': str(student.id), 'exam_id': str(exam.id)}
    first = client.post('/api/v1/diagnoses/from-exam', json=request)
    assert first.status_code == 200, first.text
    second = client.post('/api/v1/diagnoses/from-exam', json=request)
    assert second.json()['duplicate']
    assert db.scalar(select(func.count()).select_from(StudentKnowledgeState)) == 1
    assert db.scalar(select(func.count()).select_from(DiagnosisRun)) == 1
    state = db.scalar(select(StudentKnowledgeState))
    assert str(state.source_id) == first.json()['id']
    saved = client.get('/api/v1/diagnoses/' + first.json()['id']).json()
    assert saved['report']['knowledge_points'][0]['estimate']['interval_95']
    assert saved['input_snapshot']['current']['questions'][0]['score'] == 8
    request['student_id'] = str(uuid4())
    assert client.post('/api/v1/diagnoses/from-exam', json=request).status_code == 404
