from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator
from app.schemas.knowledge import StrictModel

Reason = Literal['calculation', 'concept', 'method', 'time', 'unknown']


class Tag(StrictModel):
    knowledge_point_id: UUID
    weight: float = Field(default=1, gt=0, le=100, allow_inf_nan=False)


class LossReason(StrictModel):
    category: Reason
    lost_score: float = Field(gt=0, allow_inf_nan=False)
    evidence: str = Field(min_length=1, max_length=2000)
    source: Literal['teacher', 'student', 'rubric']


class QuestionResult(StrictModel):
    question_id: UUID
    score: float = Field(ge=0, allow_inf_nan=False)
    max_score: float = Field(gt=0, allow_inf_nan=False)
    difficulty: float = Field(default=0.5, ge=0, le=1, allow_inf_nan=False)
    tags: list[Tag] = Field(default_factory=list, max_length=100)
    reasons: list[LossReason] = Field(default_factory=list, max_length=100)

    @model_validator(mode='after')
    def consistent(self):
        if self.score > self.max_score:
            raise ValueError('题目得分不能超过满分')
        if len({t.knowledge_point_id for t in self.tags}) != len(self.tags):
            raise ValueError('同一道题的知识点标签不能重复')
        if sum(r.lost_score for r in self.reasons) > self.max_score - self.score + 1e-8:
            raise ValueError('已归因失分超过实际失分')
        return self


class ExamResult(StrictModel):
    exam_id: UUID
    exam_date: date
    total_score: float = Field(ge=0, allow_inf_nan=False)
    max_score: float = Field(gt=0, allow_inf_nan=False)
    questions: list[QuestionResult] = Field(min_length=1, max_length=1000)

    @model_validator(mode='after')
    def consistent(self):
        if len({q.question_id for q in self.questions}) != len(self.questions):
            raise ValueError('考试内题目重复')
        if abs(sum(q.score for q in self.questions) - self.total_score) > 1e-6:
            raise ValueError('各题得分之和与考试总分不一致')
        if abs(sum(q.max_score for q in self.questions) - self.max_score) > 1e-6:
            raise ValueError('各题满分之和与考试满分不一致')
        return self


class DiagnosisRequest(StrictModel):
    student_id: UUID
    current: ExamResult
    history: list[ExamResult] = Field(default_factory=list, max_length=100)

    @model_validator(mode='after')
    def history_valid(self):
        exams = [self.current, *self.history]
        if len({e.exam_id for e in exams}) != len(exams):
            raise ValueError('考试记录重复，不能重复累计历史证据')
        if any(e.exam_date >= self.current.exam_date for e in self.history):
            raise ValueError('历史考试日期必须早于当前考试')
        return self


class StoredDiagnosisRequest(StrictModel):
    student_id: UUID
    exam_id: UUID
    reasons: dict[UUID, list[LossReason]] = Field(default_factory=dict)


class MasteryEstimate(StrictModel):
    index: float
    alpha: float
    beta: float
    standard_deviation: float
    interval_95: tuple[float, float]
    evidence_strength: float
    confidence: float


class KnowledgePerformance(StrictModel):
    knowledge_point_id: UUID
    allocated_score: float
    allocated_max_score: float
    allocated_lost_score: float
    observed_score_rate: float | None
    estimate: MasteryEstimate
    exam_count: int
    persistent_weakness: bool
    explanation: str
    recommendations: list[str]


class DiagnosisReport(StrictModel):
    model_version: str
    student_id: UUID
    exam_id: UUID
    total_score: float
    max_score: float
    questions: list[dict]
    knowledge_points: list[KnowledgePerformance]
    loss_by_reason: dict[str, float]
    untagged_lost_score: float
    warnings: list[str]
    methodology: list[str]
