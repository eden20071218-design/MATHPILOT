"""Synthetic data; run locally without an API key or database."""
import json
import argparse
from datetime import datetime, timedelta
from uuid import UUID
from app.schemas.planning import PlanningRequest
from app.services.planning import plan


def sample():
    start = datetime.fromisoformat('2026-10-14T19:00:00+08:00')
    return PlanningRequest(student_id=UUID(int=1), current_score=55, target_score=75,
        start_at=start, exam_at=start+timedelta(days=21), daily_minutes=60,
        availability=[{'start': start+timedelta(days=d), 'end': start+timedelta(days=d, minutes=60)} for d in range(21)],
        knowledge=[{'id': UUID(int=2), 'name': '函数', 'mastery': 0.4, 'uncertainty': 0.4, 'learning_minutes': 60},
                   {'id': UUID(int=3), 'name': '导数', 'mastery': 0.3, 'uncertainty': 0.5, 'learning_minutes': 90,
                    'exam_weight': 2, 'prerequisites': [UUID(int=2)], 'practice_rates': [0.4, 0.5]}],
        completion_rate=0.8, exam_rates=[0.5, 0.55])


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--summary', action='store_true')
    args = parser.parse_args()
    result = plan(sample())
    if args.summary:
        from collections import Counter
        result = {'status': result['status'], 'task_count': len(result['tasks']),
                  'kinds': dict(Counter(t['kind'] for t in result['tasks'])),
                  'max_daily_minutes': max(result['daily_minutes'].values(), default=0),
                  'weeks': len(result['weekly_plans']), 'unmet': result['unmet'],
                  'first_tasks': result['tasks'][:3]}
    print(json.dumps(result, ensure_ascii=False, indent=2))
