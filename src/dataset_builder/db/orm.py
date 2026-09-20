"""PostgreSQL persistence models; domain models remain independent of the ORM."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ProjectRow(Base):
    __tablename__ = "projects"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ModelConfigRow(Base):
    __tablename__ = "model_configs"
    __table_args__ = (
        Index("uq_model_configs_active_name", "name", unique=True, postgresql_where="archived_at IS NULL"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255))
    family_id: Mapped[UUID] = mapped_column(default=uuid4, index=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    base_url: Mapped[str] = mapped_column(Text)
    api_key: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(255))
    temperature: Mapped[float] = mapped_column(default=0.7)
    max_tokens: Mapped[int] = mapped_column(Integer, default=1024)
    timeout: Mapped[float] = mapped_column(default=60)
    concurrency_limit: Mapped[int] = mapped_column(Integer, default=4)
    max_retries: Mapped[int] = mapped_column(Integer, default=2)
    json_mode: Mapped[bool] = mapped_column(Boolean, default=False)
    thinking: Mapped[bool | None] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkspaceSettingsRow(Base):
    __tablename__ = "workspace_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    parser_workers: Mapped[int] = mapped_column(Integer, default=1)
    default_model_id: Mapped[UUID | None] = mapped_column(ForeignKey("model_configs.id"))


class PromptTemplateRow(Base):
    __tablename__ = "prompt_templates"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255))
    mode: Mapped[str] = mapped_column(String(32))
    instruction: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SourceDocumentRow(Base):
    __tablename__ = "source_documents"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    source_name: Mapped[str] = mapped_column(String(255))
    source_type: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    parse_status: Mapped[str] = mapped_column(String(32), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChunkRow(Base):
    __tablename__ = "chunks"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("source_documents.id"), index=True)
    index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    generation_status: Mapped[str] = mapped_column(String(32), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TrainingSampleRow(Base):
    __tablename__ = "training_samples"
    __table_args__ = (
        Index("ix_training_samples_export", "project_id", "review_status", "validation_status", "is_deleted"),
        Index("ix_training_samples_dedupe", "project_id", "content_hash"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"))
    document_id: Mapped[UUID] = mapped_column(ForeignKey("source_documents.id"), index=True)
    chunk_id: Mapped[UUID] = mapped_column(ForeignKey("chunks.id"), index=True)
    messages: Mapped[list] = mapped_column(JSONB)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    review_status: Mapped[str] = mapped_column(String(32), default="pending")
    validation_status: Mapped[str] = mapped_column(String(32), default="pending")
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ValidationIssueRow(Base):
    __tablename__ = "validation_issues"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    sample_id: Mapped[UUID] = mapped_column(ForeignKey("training_samples.id"), index=True)
    rule: Mapped[str] = mapped_column(String(100))
    severity: Mapped[str] = mapped_column(String(16))
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PipelineRunRow(Base):
    __tablename__ = "pipeline_runs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="created")
    current_stage: Mapped[str | None] = mapped_column(String(32))
    configuration: Mapped[dict] = mapped_column(JSONB, default=dict)
    total_items: Mapped[int] = mapped_column(Integer, default=0)
    completed_items: Mapped[int] = mapped_column(Integer, default=0)
    failed_items: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ExportRecordRow(Base):
    __tablename__ = "export_records"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    format: Mapped[str] = mapped_column(String(32))
    file_type: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(32), default="pending")
    sample_count: Mapped[int] = mapped_column(Integer, default=0)
    file_path: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
