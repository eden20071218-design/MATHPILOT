"""Deterministic diagnostic Agent with a replaceable measurement-model interface."""
import math
from typing import Protocol

from app.schemas.diagnosis import DiagnosisRequest, DiagnosisReport, MasteryEstimate, KnowledgePerformance


class MeasurementModel(Protocol):
    version: str

    def estimate(self, observations: list[tuple[float, float, float]]) -> MasteryEstimate:
        """Observations: score fraction, difficulty, decayed fractional item weight."""
        ...


class ShrunkEvidenceModel:
    version = 'fractional-beta-v1'

    def estimate(self, observations):
        # Fractional Beta pseudo-counts, not calibrated mastery probabilities.
        alpha, beta = 2.0, 2.0
        for rate, difficulty, weight in observations:
            alpha += weight * rate * (0.5 + difficulty)
            beta += weight * (1 - rate) * (1.5 - difficulty)
        strength = alpha + beta - 4
        mean = alpha / (alpha + beta)
        variance = alpha * beta / ((alpha + beta) ** 2 * (alpha + beta + 1))
        # Chebyshev gives >=95% posterior mass under this pseudo-count model.
        radius = math.sqrt(variance / 0.05)
        return MasteryEstimate(index=mean, alpha=alpha, beta=beta,
            standard_deviation=math.sqrt(variance), interval_95=(max(0, mean-radius), min(1, mean+radius)),
            evidence_strength=strength, confidence=strength/(strength+4))


def diagnose(request: DiagnosisRequest, model: MeasurementModel | None = None) -> DiagnosisReport:
    model = model or ShrunkEvidenceModel()
    buckets = {}
    question_reports = []
    reasons = dict.fromkeys(['calculation', 'concept', 'method', 'time', 'unknown'], 0.0)
    untagged = 0.0
    for exam in sorted([*request.history, request.current], key=lambda e: (e.exam_date, str(e.exam_id))):
        decay = 2 ** (-(request.current.exam_date-exam.exam_date).days/180)
        per_exam = {}
        for question in exam.questions:
            loss = question.max_score-question.score
            rate = question.score/question.max_score
            total_weight = sum(t.weight for t in question.tags)
            allocations = []
            for tag in question.tags:
                weight = tag.weight/total_weight
                bucket = buckets.setdefault(tag.knowledge_point_id, {'observations': [], 'score': 0., 'max': 0., 'exams': []})
                bucket['observations'].append((rate, question.difficulty, weight*decay))
                stats = per_exam.setdefault(tag.knowledge_point_id, [0., 0., 0.])
                stats[0] += question.score*weight
                stats[1] += question.max_score*weight
                stats[2] += weight
                if exam.exam_id == request.current.exam_id:
                    bucket['score'] += question.score*weight
                    bucket['max'] += question.max_score*weight
                allocations.append({'knowledge_point_id': str(tag.knowledge_point_id), 'weight': weight,
                                    'score': question.score*weight, 'max_score': question.max_score*weight, 'lost_score': loss*weight})
            if exam.exam_id == request.current.exam_id:
                classified = sum(r.lost_score for r in question.reasons)
                for reason in question.reasons:
                    reasons[reason.category] += reason.lost_score
                reasons['unknown'] += max(0, loss-classified)
                if not question.tags:
                    untagged += loss
                question_reports.append({'question_id': str(question.question_id), 'score': question.score,
                    'max_score': question.max_score, 'lost_score': loss, 'score_rate': rate,
                    'difficulty': question.difficulty, 'allocations': allocations,
                    'reported_reasons': [r.model_dump() for r in question.reasons],
                    'unknown_lost_score': max(0, loss-classified)})
        for kp, (score, maximum, evidence) in per_exam.items():
            buckets[kp]['exams'].append((exam.exam_date, score/maximum, evidence))
    performances = []
    for kp, bucket in sorted(buckets.items(), key=lambda pair: str(pair[0])):
        estimate = model.estimate(bucket['observations'])
        recent = [e for e in bucket['exams'] if (request.current.exam_date-e[0]).days <= 365][-3:]
        persistent = len(recent) == 3 and all(rate < 0.6 and evidence >= 1 for _, rate, evidence in recent)
        rate = bucket['score']/bucket['max'] if bucket['max'] else None
        explanation = (f"来自 {len(bucket['exams'])} 次考试；有效证据量 {estimate.evidence_strength:.2f}。"
                       f"先验收缩后的掌握指标为 {estimate.index:.3f}，不是单次正确率或已校准的真实掌握概率。")
        if persistent:
            explanation += '最近一年内最后三次观测均低于60%，且各有至少一道等效题证据，标记持续薄弱。'
        else:
            explanation += '未满足持续薄弱判据；这不代表已经掌握。'
        recommendations = ['补充独立知识点的小测并记录解题过程，以减少多标签题目的归因歧义。']
        if persistent:
            recommendations.append('优先复习该知识点定义与基本方法，分次练习后复测，避免仅凭单次低分调整全部计划。')
        if rate is None:
            explanation += '本次考试未覆盖该知识点，估计仅来自衰减后的历史证据。'
        performances.append(KnowledgePerformance(knowledge_point_id=kp, allocated_score=bucket['score'],
            allocated_max_score=bucket['max'], allocated_lost_score=bucket['max']-bucket['score'],
            observed_score_rate=rate, estimate=estimate, exam_count=len(bucket['exams']),
            persistent_weakness=persistent, explanation=explanation, recommendations=recommendations))
    return DiagnosisReport(model_version=model.version, student_id=request.student_id, exam_id=request.current.exam_id,
        total_score=request.current.total_score, max_score=request.current.max_score, questions=question_reports,
        knowledge_points=performances, loss_by_reason=reasons, untagged_lost_score=untagged,
        warnings=['仅凭分数不能判断计算、概念、方法或时间原因；归因采用教师、学生或评分记录，其余标为未知。',
                  '历史题目重复及知识点相关性可能影响估计；该指标和区间未经教育测量校准。'],
        methodology=['每题知识标签权重归一化，得分、满分、失分和题目证据按同一权重分配，防止重复累计。',
                     '先验 alpha=beta=2；成功证据=r*(0.5+d)，失败证据=(1-r)*(1.5-d)。难度 d 在0到1之间。',
                     '历史证据以180天为半衰期；每道题基础证据最多按一道题计算，不把每一分作为独立试验。',
                     '95%区间为伪后验方差的Chebyshev保守区间，可能覆盖[0,1]；不是能力保证区间。',
                     'confidence=有效证据/(有效证据+4)，只表示证据充分程度。'])
