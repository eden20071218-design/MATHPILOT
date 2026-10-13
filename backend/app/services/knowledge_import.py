import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.entities import KnowledgeDependency, KnowledgePoint, Question, QuestionKnowledgePoint
from app.models.knowledge import KnowledgeAlias, KnowledgeRevision, MaterialImport, MaterialSource
from app.schemas.knowledge import ImportRequest, KnowledgeContent, ParsedMaterial
from app.services.math_parser import assess, normalize_name


class KnowledgeConflict(ValueError):
    pass


def digest(value) -> str:
    encoded = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def find_point(db: Session, name: str) -> KnowledgePoint | None:
    normalized = normalize_name(name)
    alias = db.scalar(select(KnowledgeAlias).where(KnowledgeAlias.normalized_name == normalized))
    if alias:
        return db.get(KnowledgePoint, alias.knowledge_point_id)
    # Compatibility with phase-one records that predate alias indexing.
    matches = [p for p in db.scalars(select(KnowledgePoint)) if normalize_name(p.name) == normalized]
    if len(matches) > 1:
        raise KnowledgeConflict("存在同名历史知识点，需先人工消歧")
    return matches[0] if matches else None


def ensure_alias(db: Session, point: KnowledgePoint, name: str):
    normalized = normalize_name(name)
    if not normalized:
        raise KnowledgeConflict("知识点名称或别名不能为空")
    existing = db.scalar(select(KnowledgeAlias).where(KnowledgeAlias.normalized_name == normalized))
    if existing and existing.knowledge_point_id != point.id:
        raise KnowledgeConflict(f"别名 {name} 已属于其他知识点")
    if not existing:
        db.add(KnowledgeAlias(knowledge_point_id=point.id, name=name, normalized_name=normalized))
        db.flush()


def import_material(db: Session, request: ImportRequest, parsed: ParsedMaterial, target: KnowledgePoint | None = None):
    """One atomic transaction, committed by the caller. No source text is executed."""
    source = db.scalar(select(MaterialSource).where(MaterialSource.source_key == request.source_key))
    if source is None:
        source = MaterialSource(source_key=request.source_key, title=request.source_title, uri=request.source_uri)
        db.add(source)
        db.flush()
    parsed = parsed.model_copy(update={"knowledge_points": [assess(p) for p in parsed.knowledge_points]})
    if parsed.ai_generated and not parsed.model_name:
        raise KnowledgeConflict("AI 结构化结果必须提供 model_name")
    fingerprint = digest({"text": request.text.replace("\r\n", "\n").strip(),
                          "parsed": parsed.model_dump(mode="json"), "target": str(target.id) if target else None})
    previous = db.scalar(select(MaterialImport).where(
        MaterialImport.source_id == source.id,
        MaterialImport.source_version == request.source_version,
        MaterialImport.content_hash == fingerprint,
        MaterialImport.parser_version == parsed.parser_version,
    ))
    if previous:
        return {"import_id": previous.id, "source_id": source.id, "duplicate": True,
                **{key: 0 for key in previous.result}, "parsed": previous.parsed}
    counts = {"created_points": 0, "created_revisions": 0, "created_questions": 0,
              "created_links": 0, "created_dependencies": 0}
    for content in parsed.knowledge_points:
        names = [content.name, *content.aliases]
        candidates = {p.id: p for n in names if (p := find_point(db, n)) is not None}
        if target is not None:
            candidates[target.id] = target
        if len(candidates) > 1:
            raise KnowledgeConflict("名称和别名指向不同知识点，已回滚导入，需人工消歧")
        point = next(iter(candidates.values()), None)
        if point is None:
            point = KnowledgePoint(code="KP-" + digest(normalize_name(content.name))[:32], name=content.name)
            db.add(point)
            db.flush()
            counts["created_points"] += 1
        for name in names:
            ensure_alias(db, point, name)
        structured = content.model_dump(mode="json")
        # Extraction metadata must not turn the same mathematical description into a new version.
        semantic = {key: value for key, value in structured.items() if key not in ("evidence", "confidence", "review_reasons", "name", "aliases")}
        content_hash = digest({"content": semantic, "source_version": request.source_version})
        previous_revision = db.scalar(select(KnowledgeRevision).where(
            KnowledgeRevision.knowledge_point_id == point.id,
            KnowledgeRevision.source_id == source.id,
            KnowledgeRevision.content_hash == content_hash,
        ))
        if previous_revision:
            continue
        version = (db.scalar(select(func.max(KnowledgeRevision.version)).where(KnowledgeRevision.knowledge_point_id == point.id)) or 0) + 1
        if version > 1:
            content.review_reasons.append("已有其他描述或版本，请核对差异，未覆盖正式内容")
        db.add(KnowledgeRevision(
            knowledge_point_id=point.id, source_id=source.id, version=version,
            source_version=request.source_version, content_hash=content_hash,
            content=content.model_dump(mode="json"), original_text=content.evidence or request.text,
            review_status="pending", review_reasons=content.review_reasons,
            confidence=content.confidence, ai_generated=parsed.ai_generated,
            model_name=parsed.model_name, parser_version=parsed.parser_version,
        ))
        db.flush()
        counts["created_revisions"] += 1
    record = MaterialImport(source_id=source.id, source_version=request.source_version,
                            content_hash=fingerprint, parser_version=parsed.parser_version,
                            original_text=request.text, format=request.format,
                            parsed=parsed.model_dump(mode="json"), result=counts)
    db.add(record)
    db.flush()
    return {"import_id": record.id, "source_id": source.id, "duplicate": False, **counts, "parsed": record.parsed}


def creates_cycle(db: Session, prerequisite, dependent) -> bool:
    edges: dict = {}
    for edge in db.scalars(select(KnowledgeDependency)):
        edges.setdefault(edge.prerequisite_id, []).append(edge.dependent_id)
    todo, visited = [dependent], set()
    while todo:
        node = todo.pop()
        if node == prerequisite:
            return True
        if node not in visited:
            visited.add(node)
            todo.extend(edges.get(node, []))
    return False


def approve_revision(db: Session, revision: KnowledgeRevision):
    """Publish only after explicit review; unresolved references abort atomically."""
    point = db.get(KnowledgePoint, revision.knowledge_point_id)
    content = KnowledgeContent.model_validate(revision.content)
    published_version = db.scalar(select(func.max(KnowledgeRevision.version)).where(
        KnowledgeRevision.knowledge_point_id == point.id, KnowledgeRevision.review_status == "approved")) or 0
    if revision.version < published_version:
        raise KnowledgeConflict("不能用旧修订覆盖较新的已审核版本")
    for name in content.prerequisites:
        prerequisite = find_point(db, name)
        if prerequisite is None:
            raise KnowledgeConflict(f"前置知识点不存在：{name}")
        if creates_cycle(db, prerequisite.id, point.id):
            raise KnowledgeConflict(f"前置依赖将形成环：{name}")
        edge = db.scalar(select(KnowledgeDependency).where(
            KnowledgeDependency.prerequisite_id == prerequisite.id,
            KnowledgeDependency.dependent_id == point.id))
        if edge is None:
            db.add(KnowledgeDependency(prerequisite_id=prerequisite.id, dependent_id=point.id))
            db.flush()
    for example in content.examples:
        ref = "KB-" + digest(example.model_dump(exclude={"knowledge_points"}))[:60]
        question = db.scalar(select(Question).where(Question.external_ref == ref))
        if question is None:
            question = Question(external_ref=ref, stem=example.stem, answer=example.answer, explanation=example.solution)
            db.add(question)
            db.flush()
        associated = [point]
        for name in example.knowledge_points:
            related = find_point(db, name)
            if related is None:
                raise KnowledgeConflict(f"例题关联知识点不存在：{name}")
            associated.append(related)
        for related in {p.id: p for p in associated}.values():
            link = db.scalar(select(QuestionKnowledgePoint).where(
                QuestionKnowledgePoint.question_id == question.id,
                QuestionKnowledgePoint.knowledge_point_id == related.id))
            if link is None:
                db.add(QuestionKnowledgePoint(question_id=question.id, knowledge_point_id=related.id))
                db.flush()
    point.description = content.definition
    point.version = revision.version
    revision.review_status = "approved"
    revision.reviewed_at = datetime.now(timezone.utc)
