"""Synthetic demonstration, not an actual student's record. No database required."""
import json
from uuid import UUID
from app.schemas.diagnosis import DiagnosisRequest
from app.services.diagnosis import diagnose


def sample():
    def identifier(n):
        return str(UUID(int=n))
    def exam(n, day, score):
        return {'exam_id': identifier(n), 'exam_date': day, 'total_score': score, 'max_score': 20,
            'questions': [{'question_id': identifier(100+n), 'score': score, 'max_score': 20,
                'difficulty': 0.5, 'tags': [{'knowledge_point_id': identifier(2), 'weight': 1}]}]}
    current = exam(10, '2026-10-13', 8)
    current['questions'][0]['reasons'] = [
        {'category': 'calculation', 'lost_score': 3, 'evidence': '示例评分记录：展开式符号错误', 'source': 'rubric'},
        {'category': 'method', 'lost_score': 5, 'evidence': '示例教师批注：未正确构造差商', 'source': 'teacher'}]
    return DiagnosisRequest.model_validate({'student_id': identifier(1), 'current': current,
        'history': [exam(8, '2026-09-01', 6), exam(9, '2026-09-20', 8)]})


if __name__ == '__main__':
    print(json.dumps(diagnose(sample()).model_dump(mode='json'), ensure_ascii=False, indent=2))
