from uuid import UUID
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.entities import KnowledgePoint
from app.models.knowledge import KnowledgeAlias, KnowledgeRevision, MaterialImport, MaterialSource
from app.schemas.knowledge import (ImportRequest, ImportResult, ParsedMaterial, RevisionCreate,
                                   RevisionRead, ReviewRequest, StructuredImportRequest)
from app.services.knowledge_import import KnowledgeConflict, approve_revision, import_material
from app.services.math_parser import normalize_name, parse_text

router = APIRouter(prefix="/knowledge", tags=["Knowledge management"])


def parse(request: ImportRequest) -> ParsedMaterial:
    try:
        return parse_text(request.text)
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc


def execute_import(db, request, parsed, target=None):
    try:
        result = import_material(db, request, parsed, target)
        db.commit()
        return result
    except (KnowledgeConflict, IntegrityError) as exc:
        db.rollback()
        detail = str(exc) if isinstance(exc, KnowledgeConflict) else "并发导入或唯一约束冲突，请重试"
        raise HTTPException(409, detail=detail) from exc


@router.post("/parse", response_model=ParsedMaterial)
def preview(request: ImportRequest):
    """Parse without persistence. No external model or network call."""
    return parse(request)


@router.post("/imports", response_model=ImportResult)
def import_text(request: ImportRequest, db: Session = Depends(get_db)):
    return execute_import(db, request, parse(request))


@router.post("/imports/structured", response_model=ImportResult)
def import_structured(request: StructuredImportRequest, db: Session = Depends(get_db)):
    """Validate externally extracted AI/manual JSON using the same staging workflow."""
    return execute_import(db, request, request.parsed)


@router.get("/imports/{import_id}")
def get_import(import_id: UUID, db: Session = Depends(get_db)):
    record = db.get(MaterialImport, import_id)
    if record is None:
        raise HTTPException(404, "Import not found")
    return record


@router.get("/sources")
def sources(db: Session = Depends(get_db), limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)):
    return list(db.scalars(select(MaterialSource).order_by(MaterialSource.created_at, MaterialSource.id).offset(offset).limit(limit)))


@router.post("/points", response_model=ImportResult, status_code=201)
def create_point(request: RevisionCreate, db: Session = Depends(get_db)):
    material = ImportRequest(source_key=request.source_key, source_title=request.source_title,
                             text=request.content.evidence or request.content.model_dump_json())
    return execute_import(db, material, ParsedMaterial(parser_version="manual-v1", knowledge_points=[request.content]))


@router.get("/points")
def query_points(q: str | None = None, limit: int = Query(100, ge=1, le=500),
                 offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    statement = select(KnowledgePoint)
    if q:
        matching_aliases = select(KnowledgeAlias.knowledge_point_id).where(
            KnowledgeAlias.normalized_name.contains(normalize_name(q), autoescape=True))
        statement = statement.where(or_(KnowledgePoint.name.contains(q, autoescape=True), KnowledgePoint.id.in_(matching_aliases)))
    return list(db.scalars(statement.order_by(KnowledgePoint.created_at, KnowledgePoint.id).offset(offset).limit(limit)))


@router.get("/points/{point_id}")
def detail(point_id: UUID, db: Session = Depends(get_db)):
    point = db.get(KnowledgePoint, point_id)
    if point is None:
        raise HTTPException(404, "Knowledge point not found")
    revisions = list(db.scalars(select(KnowledgeRevision).where(KnowledgeRevision.knowledge_point_id == point_id).order_by(KnowledgeRevision.version.desc())))
    approved = next((r for r in revisions if r.review_status == "approved"), None)
    return {"point": point, "aliases": list(db.scalars(select(KnowledgeAlias.name).where(KnowledgeAlias.knowledge_point_id == point_id))),
            "published": serialize(approved) if approved else None, "revisions": [serialize(r) for r in revisions]}


@router.patch("/points/{point_id}", response_model=ImportResult)
def update_point(point_id: UUID, request: RevisionCreate, db: Session = Depends(get_db)):
    point = db.get(KnowledgePoint, point_id)
    if point is None:
        raise HTTPException(404, "Knowledge point not found")
    material = ImportRequest(source_key=request.source_key, source_title=request.source_title,
                             text=request.content.evidence or request.content.model_dump_json())
    return execute_import(db, material, ParsedMaterial(parser_version="manual-v1", knowledge_points=[request.content]), point)


def serialize(revision):
    return RevisionRead(**{key: getattr(revision, key) for key in RevisionRead.model_fields})


@router.get("/revisions", response_model=list[RevisionRead])
def query_revisions(status: str = Query("pending", pattern="^(pending|approved|rejected)$"),
                    limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    revisions = db.scalars(select(KnowledgeRevision).where(KnowledgeRevision.review_status == status)
                           .order_by(KnowledgeRevision.created_at, KnowledgeRevision.id).offset(offset).limit(limit))
    return [serialize(r) for r in revisions]


@router.post("/revisions/{revision_id}/review", response_model=RevisionRead)
def review(revision_id: UUID, request: ReviewRequest, db: Session = Depends(get_db)):
    revision = db.get(KnowledgeRevision, revision_id)
    if revision is None:
        raise HTTPException(404, "Revision not found")
    if revision.review_status != "pending":
        raise HTTPException(409, "修订已经审核，请创建新修订")
    try:
        if request.status == "approved":
            approve_revision(db, revision)
        else:
            revision.review_status = "rejected"
            revision.reviewed_at = datetime.now(timezone.utc)
        revision.reviewer = request.reviewer
        revision.review_note = request.note
        db.commit()
        return serialize(revision)
    except (KnowledgeConflict, IntegrityError) as exc:
        db.rollback()
        raise HTTPException(409, detail=str(exc) if isinstance(exc, KnowledgeConflict) else "审核发布发生约束冲突") from exc
