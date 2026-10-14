from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pydantic import AwareDatetime, Field, model_validator
from app.schemas.knowledge import StrictModel


class PlanningKnowledge(StrictModel):
    id: UUID
    name: str = Field(min_length=1, max_length=200)
    mastery: float = Field(ge=0, le=1, allow_inf_nan=False)
    uncertainty: float = Field(ge=0, le=1, allow_inf_nan=False)
    exam_weight: float = Field(default=1, gt=0, le=100, allow_inf_nan=False)
    learning_gain: float = Field(default=1, gt=0, le=10, allow_inf_nan=False)
    learning_minutes: int = Field(default=30, ge=10, le=240)
    prerequisites: list[UUID] = Field(default_factory=list)
    practice_rates: list[float] = Field(default_factory=list, max_length=100)

    @model_validator(mode='after')
    def rates(self):
        if any(not 0 <= r <= 1 for r in self.practice_rates):
            raise ValueError('练习表现必须在0到1之间')
        return self


class Availability(StrictModel):
    start: AwareDatetime
    end: AwareDatetime


class PlannedTask(StrictModel):
    id: UUID = Field(default_factory=uuid4)
    knowledge_point_id: UUID
    kind: Literal['learn', 'review', 'assessment'] = 'learn'
    content: str
    minutes: int = Field(gt=0)
    difficulty: float = Field(ge=0, le=1)
    completion_criterion: str
    start: AwareDatetime
    end: AwareDatetime
    status: Literal['scheduled', 'pending', 'completed', 'in_progress', 'skipped', 'cancelled'] = 'scheduled'
    locked: bool = False


class PlanningRequest(StrictModel):
    student_id: UUID
    goal_id: UUID | None = None
    previous_run_id: UUID | None = None
    current_score: float = Field(ge=0, allow_inf_nan=False)
    target_score: float = Field(ge=0, allow_inf_nan=False)
    full_score: float = Field(default=100, gt=0, allow_inf_nan=False)
    start_at: AwareDatetime
    exam_at: AwareDatetime
    timezone: str = 'Asia/Shanghai'
    daily_minutes: int = Field(default=60, ge=0, le=1440)
    availability: list[Availability] = Field(min_length=1, max_length=1000)
    knowledge: list[PlanningKnowledge] = Field(min_length=1, max_length=200)
    existing_tasks: list[PlannedTask] = Field(default_factory=list, max_length=5000)
    completion_rate: float = Field(default=1, ge=0, le=1, allow_inf_nan=False)
    exam_rates: list[float] = Field(default_factory=list, max_length=100)
    reason: str = Field(default='首次规划', min_length=1, max_length=2000)
    use_ai: bool = False

    @model_validator(mode='after')
    def consistent(self):
        try:
            zone = ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError('无效时区') from exc
        if not self.start_at < self.exam_at or (self.exam_at-self.start_at).days > 366:
            raise ValueError('规划区间应为正且不超过366天')
        if max(self.current_score, self.target_score) > self.full_score:
            raise ValueError('成绩或目标不能超过满分')
        if any(not 0 <= r <= 1 for r in self.exam_rates):
            raise ValueError('历史考试得分率须在0到1之间')
        ids = {k.id for k in self.knowledge}
        if len(ids) != len(self.knowledge):
            raise ValueError('知识点重复')
        for k in self.knowledge:
            if k.id in k.prerequisites or not set(k.prerequisites) <= ids:
                raise ValueError('前置知识缺失或指向自身')
        if len({t.id for t in self.existing_tasks}) != len(self.existing_tasks):
            raise ValueError('任务ID重复')
        for window in self.availability:
            if window.start >= window.end or window.start.astimezone(zone).date() != window.end.astimezone(zone).date():
                raise ValueError('可用时间必须为同一当地日期内的正时段')
        return self
