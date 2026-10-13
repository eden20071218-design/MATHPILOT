"""Validated contracts shared by parsers, AI adapters and HTTP endpoints."""
from typing import Literal
from uuid import UUID
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Formula(StrictModel):
    expression: str = Field(min_length=1, max_length=4000)
    conditions: list[str] = Field(default_factory=list, max_length=50)


class Example(StrictModel):
    stem: str = Field(min_length=1, max_length=10000)
    answer: str | None = Field(default=None, max_length=10000)
    solution: str | None = Field(default=None, max_length=20000)
    knowledge_points: list[str] = Field(default_factory=list, max_length=50)


class KnowledgeContent(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    aliases: list[str] = Field(default_factory=list, max_length=50)
    definition: str | None = Field(default=None, max_length=20000)
    theorems: list[str] = Field(default_factory=list, max_length=100)
    formulas: list[Formula] = Field(default_factory=list, max_length=100)
    conditions: list[str] = Field(default_factory=list, max_length=100)
    question_types: list[str] = Field(default_factory=list, max_length=100)
    methods: list[str] = Field(default_factory=list, max_length=100)
    prerequisites: list[str] = Field(default_factory=list, max_length=50)
    examples: list[Example] = Field(default_factory=list, max_length=100)
    evidence: str = Field(default="", max_length=100000)
    confidence: float = Field(default=0.5, ge=0, le=1)
    review_reasons: list[str] = Field(default_factory=list)


class ParsedMaterial(StrictModel):
    parser_version: str = "rules-v1"
    ai_generated: bool = False
    model_name: str | None = None
    knowledge_points: list[KnowledgeContent] = Field(min_length=1, max_length=200)
    warnings: list[str] = Field(default_factory=list)


class ImportRequest(StrictModel):
    source_key: str = Field(min_length=1, max_length=200)
    source_title: str = Field(min_length=1, max_length=300)
    source_uri: str | None = Field(default=None, max_length=2000)
    source_version: str = Field(default="1", min_length=1, max_length=100)
    format: Literal["text", "markdown"] = "markdown"
    text: str = Field(min_length=1, max_length=200000)

    @field_validator("text")
    @classmethod
    def meaningful_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text must contain mathematical material")
        return value


class StructuredImportRequest(ImportRequest):
    """For externally produced structured outputs; never execute source instructions."""
    parsed: ParsedMaterial


class RevisionCreate(StrictModel):
    source_key: str = Field(min_length=1, max_length=200)
    source_title: str = Field(min_length=1, max_length=300)
    content: KnowledgeContent


class ReviewRequest(StrictModel):
    status: Literal["approved", "rejected"]
    reviewer: str = Field(min_length=1, max_length=200)
    note: str = Field(min_length=1, max_length=10000)


class RevisionRead(StrictModel):
    id: UUID
    knowledge_point_id: UUID
    source_id: UUID
    version: int
    source_version: str
    parser_version: str
    review_status: str
    content: KnowledgeContent
    ai_generated: bool
    model_name: str | None
    confidence: float
    review_reasons: list[str]
    reviewer: str | None
    review_note: str | None
    original_text: str
    reviewed_at: datetime | None


class ImportResult(StrictModel):
    import_id: UUID
    source_id: UUID
    duplicate: bool
    created_points: int
    created_revisions: int
    created_questions: int
    created_links: int
    created_dependencies: int
    parsed: ParsedMaterial

