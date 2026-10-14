import json as json_module

import httpx
import pytest

from app.core.config import settings
from app.api.student import GenerateInput
from app.schemas.planning import PlannedTask
from app.services.planning import plan
from examples.plan_learning import sample


def test_deepseek_suggestion_is_opt_in_and_does_not_set_schedule(monkeypatch):
    request = sample()
    request.use_ai = True
    monkeypatch.setattr(settings, 'deepseek_enabled', True)
    monkeypatch.setattr(settings, 'deepseek_api_key', 'test-key')
    monkeypatch.setattr(settings, 'deepseek_model', 'deepseek-flash')
    calls = []

    class FakeClient:
        def __init__(self, timeout):
            assert timeout == 8

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, url, headers, json):
            calls.append((url, headers, json))
            point = request.knowledge[0]
            body = {'suggestions': [{'knowledge_point_id': str(point.id),
                'content': '完成函数基础例题', 'completion_criterion': '提交两题完整过程',
                'reason': '先巩固函数定义'}]}
            return httpx.Response(200, json={'choices': [{'finish_reason': 'stop',
                'message': {'content': json_module.dumps(body)}}]},
                request=httpx.Request('POST', url))

    monkeypatch.setattr('app.services.deepseek_planning.httpx.Client', FakeClient)
    result = plan(request)
    assert result['ai']['status'] == 'used'
    assert calls[0][0] == 'https://api.deepseek.com/chat/completions'
    assert calls[0][2]['model'] == 'deepseek-flash'
    assert 'student_id' not in calls[0][2]['messages'][1]['content']
    assert any(t['content'] == '完成函数基础例题' for t in result['tasks'])
    tasks = [PlannedTask.model_validate(t) for t in result['tasks']]
    assert all(a.end <= b.start for a, b in zip(tasks, tasks[1:]))
    assert max(result['daily_minutes'].values()) <= request.daily_minutes


def test_no_key_keeps_deterministic_planning(monkeypatch):
    request = sample()
    request.use_ai = True
    monkeypatch.setattr(settings, 'deepseek_enabled', True)
    monkeypatch.setattr(settings, 'deepseek_api_key', '')
    result = plan(request)
    assert result['ai']['status'] == 'not_configured'
    assert result['tasks']


def test_invalid_model_response_falls_back(monkeypatch):
    request = sample()
    request.use_ai = True
    monkeypatch.setattr(settings, 'deepseek_enabled', True)
    monkeypatch.setattr(settings, 'deepseek_api_key', 'test-key')

    class FakeClient:
        def __init__(self, timeout):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, url, headers, json):
            return httpx.Response(200, json={'choices': [{'finish_reason': 'stop',
                'message': {'content': '{"suggestions":[{"knowledge_point_id":"bad"}]}'}}]},
                request=httpx.Request('POST', url))

    monkeypatch.setattr('app.services.deepseek_planning.httpx.Client', FakeClient)
    result = plan(request)
    assert result['ai']['status'] == 'fallback'
    assert result['tasks']


def test_default_request_never_calls_model(monkeypatch):
    monkeypatch.setattr(settings, 'deepseek_enabled', True)
    monkeypatch.setattr(settings, 'deepseek_api_key', 'test-key')
    def unexpected(*args, **kwargs):
        raise AssertionError('unexpected model call')
    monkeypatch.setattr('app.services.deepseek_planning.httpx.Client', unexpected)
    assert plan(sample())['ai']['status'] == 'not_requested'


def test_student_key_is_per_request_and_not_in_result(monkeypatch):
    request = sample()
    request.use_ai = True
    monkeypatch.setattr(settings, 'deepseek_enabled', False)
    monkeypatch.setattr(settings, 'deepseek_api_key', '')
    received = []

    class FakeClient:
        def __init__(self, timeout):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, url, headers, json):
            received.append(headers['Authorization'])
            return httpx.Response(200, json={'choices': [{'finish_reason': 'stop',
                'message': {'content': '{"suggestions":[]}'}}]}, request=httpx.Request('POST', url))

    monkeypatch.setattr('app.services.deepseek_planning.httpx.Client', FakeClient)
    result = plan(request, ai_api_key='private-test-key')
    assert received == ['Bearer private-test-key']
    assert 'private-test-key' not in json_module.dumps(result)
    assert 'private-test-key' not in request.model_dump_json()


def test_student_key_requires_explicit_opt_in_and_is_redacted():
    with pytest.raises(ValueError, match='明确开启'):
        GenerateInput(deepseek_api_key='private-test-key')
    data = GenerateInput(use_ai=True, deepseek_api_key='private-test-key')
    assert 'private-test-key' not in repr(data)
    with pytest.raises(ValueError, match='自己的 API Key'):
        GenerateInput(use_ai=True)
