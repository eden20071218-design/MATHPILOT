import enum
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.entities import (
    Exam,
    ExamQuestion,
    KnowledgeDependency,
    KnowledgePoint,
    LearningGoal,
    LearningPlan,
    LearningTask,
    Notification,
    Question,
    QuestionKnowledgePoint,
    Student,
    StudentKnowledgeState,
    TaskAttempt,
)

router = APIRouter()

RESOURCES = {
    "students": Student,
    "exams": Exam,
    "exam-questions": ExamQuestion,
    "knowledge-points": KnowledgePoint,
    "knowledge-dependencies": KnowledgeDependency,
    "questions": Question,
    "question-knowledge-points": QuestionKnowledgePoint,
    "student-knowledge-states": StudentKnowledgeState,
    "learning-goals": LearningGoal,
    "learning-plans": LearningPlan,
    "learning-tasks": LearningTask,
    "task-attempts": TaskAttempt,
    "notifications": Notification,
}


def _columns(model: type) -> set[str]:
    return {column.key for column in model.__table__.columns}


def _writable(model: type, payload: dict[str, Any]) -> dict[str, Any]:
    blocked = {"id", "created_at", "updated_at"}
    unknown = set(payload) - _columns(model)
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown fields: {', '.join(sorted(unknown))}")
    columns = {column.key: column for column in model.__table__.columns}
    result: dict[str, Any] = {}
    for key, value in payload.items():
        if key in blocked or value is None:
            if key not in blocked:
                result[key] = value
            continue
        target_type = columns[key].type.python_type
        try:
            if target_type is UUID and not isinstance(value, UUID):
                value = UUID(value)
            elif target_type is datetime and isinstance(value, str):
                value = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if value.tzinfo is not None:
                    value = value.astimezone(timezone.utc)
            elif target_type is date and isinstance(value, str):
                value = date.fromisoformat(value)
            elif target_type is Decimal and not isinstance(value, Decimal):
                value = Decimal(str(value))
            elif isinstance(target_type, type) and issubclass(target_type, enum.Enum):
                value = target_type(value)
        except (TypeError, ValueError, InvalidOperation) as exc:
            raise HTTPException(status_code=422, detail=f"Invalid value for {key}") from exc
        result[key] = value
    return result


def _commit(db: Session, instance: Any) -> Any:
    try:
        if isinstance(instance, LearningTask):
            db.flush()
            from app.services.reminders import sync_task
            sync_task(db, instance)
        elif isinstance(instance, LearningPlan):
            db.flush()
            from app.services.reminders import sync_task
            for task in db.scalars(select(LearningTask).where(LearningTask.plan_id == instance.id)):
                sync_task(db, task)
        db.commit()
        db.refresh(instance)
        return instance
    except (IntegrityError, StatementError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Constraint or value validation failed") from exc


def register_resource(resource: str, model: type) -> None:
    tag = resource.replace("-", " ").title()

    @router.post(f"/{resource}", status_code=status.HTTP_201_CREATED, tags=[tag], name=f"create_{resource}")
    def create(payload: dict[str, Any] = Body(...), db: Session = Depends(get_db)):
        instance = model(**_writable(model, payload))
        db.add(instance)
        return _commit(db, instance)

    @router.get(f"/{resource}", tags=[tag], name=f"list_{resource}")
    def list_items(
        offset: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=500),
        db: Session = Depends(get_db),
    ):
        return list(db.scalars(select(model).offset(offset).limit(limit)).all())

    @router.get(f"/{resource}/{{item_id}}", tags=[tag], name=f"get_{resource}")
    def get(item_id: UUID, db: Session = Depends(get_db)):
        instance = db.get(model, item_id)
        if instance is None:
            raise HTTPException(status_code=404, detail="Resource not found")
        return instance

    @router.patch(f"/{resource}/{{item_id}}", tags=[tag], name=f"update_{resource}")
    def update(item_id: UUID, payload: dict[str, Any] = Body(...), db: Session = Depends(get_db)):
        instance = db.get(model, item_id)
        if instance is None:
            raise HTTPException(status_code=404, detail="Resource not found")
        for key, value in _writable(model, payload).items():
            setattr(instance, key, value)
        return _commit(db, instance)

    @router.delete(
        f"/{resource}/{{item_id}}",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=[tag],
        name=f"delete_{resource}",
    )
    def delete(item_id: UUID, db: Session = Depends(get_db)):
        instance = db.get(model, item_id)
        if instance is None:
            raise HTTPException(status_code=404, detail="Resource not found")
        try:
            db.delete(instance)
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(status_code=409, detail="Resource is still referenced") from exc
        return Response(status_code=status.HTTP_204_NO_CONTENT)


for resource_name, resource_model in RESOURCES.items():
    register_resource(resource_name, resource_model)

