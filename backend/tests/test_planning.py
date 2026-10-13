from datetime import timedelta
from uuid import UUID
import pytest
from sqlalchemy import select, func
from app.schemas.planning import PlannedTask
from app.services.planning import plan, validate, PlanningConflict
from examples.plan_learning import sample
from app.models.entities import Student, KnowledgePoint, KnowledgeDependency, LearningGoal, LearningTask, TaskAttempt
from app.models.planning import PlanningRun


def test_real_graph_schedules_dependencies_limits_reviews_and_tests():
    request = sample()
    result = plan(request)
    tasks = [PlannedTask.model_validate(t) for t in result['tasks']]
    assert all(a.end <= b.start for a,b in zip(tasks, tasks[1:]))
    assert max(result['daily_minutes'].values()) <= 60
    foundation = [t for t in tasks if t.kind == 'learn' and t.knowledge_point_id == UUID(int=2)]
    dependent = [t for t in tasks if t.kind == 'learn' and t.knowledge_point_id == UUID(int=3)]
    assert max(t.end for t in foundation) <= min(t.start for t in dependent)
    assert {t.kind for t in tasks} == {'learn', 'review', 'assessment'}
    assert result['stages'] and result['weekly_plans']
    assert all(t.completion_criterion and t.content and t.end <= request.exam_at for t in tasks)


def test_no_capacity_is_partial_not_overbooked():
    result = plan(sample().model_copy(update={'daily_minutes': 0}))
    assert result['status'] == 'partial' and result['unmet'] and not result['tasks']


def test_cycle_rejected():
    request = sample()
    request.knowledge[0].prerequisites = [request.knowledge[1].id]
    with pytest.raises(PlanningConflict, match='环'):
        plan(request)


def test_preserve_completed_in_progress_and_locked():
    request = sample()
    original = [PlannedTask.model_validate(t) for t in plan(request)['tasks'][:3]]
    original[0].status = 'completed'
    original[1].status = 'in_progress'
    original[2].locked = True
    request.existing_tasks = original
    result = plan(request)
    tasks = {t['id']: t for t in result['tasks']}
    for task in original:
        assert tasks[str(task.id)] == task.model_dump(mode='json')


def test_conflicting_locks_rejected():
    request = sample()
    task = PlannedTask.model_validate(plan(request)['tasks'][0])
    task.locked = True
    second = task.model_copy(update={'id': UUID(int=900)})
    request.existing_tasks = [task, second]
    with pytest.raises(PlanningConflict, match='冲突'):
        plan(request)


def test_feedback_changes_priority_and_load():
    request = sample()
    first = plan(request)
    request.knowledge[1].practice_rates = [0.1, 0.1]
    request.completion_rate = 0.3
    request.reason = '练习得分率下降且任务完成率降低'
    second = plan(request)
    assert second['priorities'][str(UUID(int=3))]['score'] > first['priorities'][str(UUID(int=3))]['score']
    assert max(second['daily_minutes'].values()) <= int(60*(0.6+0.4*0.3))
    assert request.reason in second['adjustment_reasons']


def test_independent_validator_rejects_tampered_schedule():
    request = sample()
    result = plan(request)
    tasks = [PlannedTask.model_validate(t) for t in result['tasks']]
    tasks[1].start = tasks[0].start
    tasks[1].end = tasks[1].start + timedelta(minutes=tasks[1].minutes)
    with pytest.raises(PlanningConflict):
        validate({'request': request, 'tasks': tasks, 'reasons': [], 'priorities': {}, 'unmet': []})


def test_save_replan_and_retry(client, db):
    request = sample()
    student = Student(id=request.student_id, email='plan@example.com', display_name='模拟学生')
    db.add(student)
    db.add_all([KnowledgePoint(id=k.id, name=k.name, code=k.name) for k in request.knowledge])
    db.flush()
    goal = LearningGoal(student_id=student.id, title='目标75', target_score=75, target_date=request.exam_at.date())
    db.add(goal); db.commit()
    request.goal_id = goal.id
    payload = request.model_dump(mode='json')
    response = client.post('/api/v1/planning/runs', json=payload)
    assert response.status_code == 200, response.text
    first = response.json()
    retry = client.post('/api/v1/planning/runs', json=payload)
    assert retry.json()['duplicate'] is True
    assert db.scalar(select(func.count()).select_from(PlanningRun)) == 1
    task = db.get(LearningTask, UUID(first['tasks'][0]['id']))
    task.status = 'completed'
    db.add(TaskAttempt(task_id=task.id, attempt_number=1, started_at=request.start_at-timedelta(days=1),
                       completed_at=request.start_at-timedelta(hours=1), result_data={'score_rate': 0.2}))
    db.commit()
    payload['previous_run_id'] = first['id']
    payload['reason'] = '根据已完成任务重新规划'
    second = client.post('/api/v1/planning/runs', json=payload)
    assert second.status_code == 200, second.text
    assert any(t['id'] == str(task.id) and t['status'] == 'completed' for t in second.json()['tasks'])
    db.refresh(task)
    assert task.status == 'completed'
    assert db.scalar(select(func.count()).select_from(PlanningRun)) == 2
    assert client.get('/api/v1/planning/runs/' + second.json()['id']).status_code == 200
    saved = client.get('/api/v1/planning/runs/' + second.json()['id']).json()
    assert saved['request']['knowledge'][0]['practice_rates'] == [0.2]


def test_short_daily_budget_is_split():
    request = sample().model_copy(update={'daily_minutes': 15})
    result = plan(request)
    assert result['tasks']
    assert max(result['daily_minutes'].values()) <= 15


def test_database_dependency_cannot_be_omitted(client, db):
    request = sample()
    db.add(Student(id=request.student_id, email='dependency@example.com', display_name='Demo'))
    db.add_all([KnowledgePoint(id=k.id, name=k.name, code=k.name) for k in request.knowledge])
    db.flush()
    goal = LearningGoal(student_id=request.student_id, title='Goal', target_date=request.exam_at.date())
    db.add(goal)
    db.add(KnowledgeDependency(prerequisite_id=request.knowledge[0].id, dependent_id=request.knowledge[1].id))
    db.commit()
    request.goal_id = goal.id
    request.knowledge = [request.knowledge[1]]
    request.knowledge[0].prerequisites = []
    response = client.post('/api/v1/planning/runs', json=request.model_dump(mode='json'))
    assert response.status_code == 422
    assert db.scalar(select(func.count()).select_from(PlanningRun)) == 0


def test_bad_timezone_api(client):
    data = sample().model_dump(mode='json')
    data['timezone'] = 'invalid/zone'
    assert client.post('/api/v1/planning/preview', json=data).status_code == 422
