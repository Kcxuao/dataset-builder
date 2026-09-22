"""Framework-independent data models for the dataset pipeline."""

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(UTC)


class MessageRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class ParseStatus(StrEnum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"


class GenerationStatus(StrEnum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"


class ReviewStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ValidationStatus(StrEnum):
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"


class IssueSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


class PipelineStatus(StrEnum):
    CREATED = "created"
    IMPORTING = "importing"
    PARSING = "parsing"
    SPLITTING = "splitting"
    GENERATING = "generating"
    CLEANING = "cleaning"
    VALIDATING = "validating"
    AUGMENTING = "augmenting"
    DISTILLING = "distilling"
    READY_FOR_REVIEW = "ready_for_review"
    COMPLETED = "completed"
    FAILED = "failed"


class ExportStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class ExportFormat(StrEnum):
    ALPACA = "alpaca"
    SHAREGPT = "sharegpt"
    SHAREGPT_PREFERENCE = "sharegpt_preference"


class DatasetType(StrEnum):
    SFT = "sft"
    DPO = "dpo"


class ExportFileType(StrEnum):
    JSON = "json"
    JSONL = "jsonl"


class SourceDocument(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    source_name: str
    source_type: str
    content: str
    metadata: dict[str, object] = Field(default_factory=dict)
    parse_status: ParseStatus = ParseStatus.PENDING
    created_at: datetime = Field(default_factory=utc_now)


class Chunk(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    document_id: UUID
    index: int = Field(ge=0)
    content: str
    content_hash: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)
    generation_status: GenerationStatus = GenerationStatus.PENDING
    created_at: datetime = Field(default_factory=utc_now)


class Message(BaseModel):
    role: MessageRole
    content: str


class TrainingSample(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    document_id: UUID
    chunk_id: UUID
    messages: list[Message]
    metadata: dict[str, object] = Field(default_factory=dict)
    content_hash: str | None = None
    review_status: ReviewStatus = ReviewStatus.PENDING
    validation_status: ValidationStatus = ValidationStatus.PENDING
    is_deleted: bool = False
    parent_sample_id: UUID | None = None
    generation_run_id: UUID | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class PreferencePair(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    context_messages: list[Message]
    chosen_response: Message
    rejected_response: Message
    chosen_sample_id: UUID | None = None
    rejected_sample_id: UUID | None = None
    document_id: UUID | None = None
    chunk_id: UUID | None = None
    source_type: str = "manual"
    source_decision_id: UUID | None = None
    content_hash: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)
    review_status: ReviewStatus = ReviewStatus.PENDING
    validation_status: ValidationStatus = ValidationStatus.PENDING
    is_deleted: bool = False
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ValidationIssue(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    sample_id: UUID
    rule: str
    severity: IssueSeverity
    message: str
    created_at: datetime = Field(default_factory=utc_now)


class PipelineRun(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    status: PipelineStatus = PipelineStatus.CREATED
    current_stage: PipelineStatus | None = None
    configuration: dict[str, object] = Field(default_factory=dict)
    total_items: int = Field(default=0, ge=0)
    completed_items: int = Field(default=0, ge=0)
    failed_items: int = Field(default=0, ge=0)
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class ExportRecord(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    format: ExportFormat
    file_type: ExportFileType
    status: ExportStatus = ExportStatus.PENDING
    sample_count: int = Field(default=0, ge=0)
    file_path: str | None = None
    error_message: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime | None = None
