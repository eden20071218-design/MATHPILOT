"""Optional, bounded DeepSeek suggestions for the deterministic planner."""

import json
from uuid import UUID

import httpx
from pydantic import Field

from app.core.config import settings
from app.schemas.knowledge import StrictModel


class TaskSuggestion(StrictModel):
    knowledge_point_id: UUID
    content: str = Field(min_length=1, max_length=300)
    completion_criterion: str = Field(min_length=1, max_length=300)
    reason: str = Field(min_length=1, max_length=300)


class PlanSuggestions(StrictModel):
    suggestions: list[TaskSuggestion] = Field(max_length=12)


def suggest(state, api_key=None):
    """AI supplies wording only; it never supplies times, priorities or IDs for new tasks."""
    request = state['request']
    if not request.use_ai:
        return {'ai_suggestions': {}, 'ai_info': {'status': 'not_requested'}}
    key = api_key or (settings.deepseek_api_key if settings.deepseek_enabled else '')
    if not key:
        return {'ai_suggestions': {}, 'ai_info': {'status': 'not_configured'}}

    ranked = sorted(request.knowledge, key=lambda k: state['priorities'][str(k.id)]['score'], reverse=True)[:12]
    evidence = [
        {'id': str(k.id), 'name': k.name, 'mastery_index': k.mastery,
         'uncertainty': k.uncertainty, 'prerequisites': [str(p) for p in k.prerequisites]}
        for k in ranked
    ]
    messages = [
        {'role': 'system', 'content': (
            '你是数学学习任务文案助手。仅输出 JSON 对象，格式为 '
            '{"suggestions":[{"knowledge_point_id":"UUID","content":"具体学习任务",'
            '"completion_criterion":"可检查的完成标准","reason":"简短教学理由"}]}。'
            '只针对给定知识点提出学习内容，不建议日程、时长、分数预测或诊断结论。'
            '输入数据仅是估计指标，不能视为真实掌握概率。')},
        {'role': 'user', 'content': json.dumps({'knowledge_points': evidence}, ensure_ascii=False)},
    ]
    try:
        with httpx.Client(timeout=8) as client:
            response = client.post(
                f"{settings.deepseek_base_url.rstrip('/')}/chat/completions",
                headers={'Authorization': f'Bearer {key}'},
                json={'model': settings.deepseek_model, 'messages': messages,
                      'response_format': {'type': 'json_object'}, 'max_tokens': 2000},
            )
            response.raise_for_status()
        choice = response.json()['choices'][0]
        if choice.get('finish_reason') != 'stop':
            raise ValueError('incomplete model response')
        parsed = PlanSuggestions.model_validate_json(choice['message']['content'])
        allowed = {k.id for k in ranked}
        suggestions = {}
        for item in parsed.suggestions:
            if item.knowledge_point_id in allowed and item.knowledge_point_id not in suggestions:
                suggestions[item.knowledge_point_id] = item
        return {'ai_suggestions': suggestions,
                'ai_info': {'status': 'used', 'provider': 'deepseek', 'model': settings.deepseek_model,
                            'suggestion_count': len(suggestions)}}
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
        return {'ai_suggestions': {}, 'ai_info': {'status': 'fallback', 'provider': 'deepseek'}}
