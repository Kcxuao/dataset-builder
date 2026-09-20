from uuid import uuid4

import pytest
from pydantic import ValidationError

from dataset_builder.models import (
    Chunk,
    ExportFileType,
    ExportFormat,
    ExportRecord,
    Message,
    MessageRole,
    PipelineRun,
    ReviewStatus,
    SourceDocument,
    TrainingSample,
    ValidationIssue,
)


def test_sample_preserves_source_lineage() -> None:
    project_id = uuid4()
    document = SourceDocument(
        project_id=project_id,
        source_name="guide.md",
        source_type="markdown",
        content="Text",
    )
    chunk = Chunk(document_id=document.id, index=0, content="Text")
    sample = TrainingSample(
        project_id=project_id,
        document_id=document.id,
        chunk_id=chunk.id,
        messages=[
            Message(role=MessageRole.USER, content="Question"),
            Message(role=MessageRole.ASSISTANT, content="Answer"),
        ],
    )

    assert sample.document_id == document.id
    assert sample.chunk_id == chunk.id
    assert sample.review_status is ReviewStatus.PENDING
    assert sample.model_dump(mode="json")["messages"][0]["role"] == "user"
    assert sample.created_at.tzinfo is not None


def test_required_fields_and_message_role_are_checked() -> None:
    with pytest.raises(ValidationError):
        SourceDocument(source_name="guide.md", source_type="markdown", content="Text")
    with pytest.raises(ValidationError):
        Message(role="tool", content="Unsupported")


def test_status_and_export_enums_are_checked() -> None:
    project_id = uuid4()
    run = PipelineRun(project_id=project_id)
    record = ExportRecord(
        project_id=project_id,
        format=ExportFormat.ALPACA,
        file_type=ExportFileType.JSONL,
    )

    assert run.status == "created"
    assert record.status == "pending"
    with pytest.raises(ValidationError):
        ExportRecord(project_id=project_id, format="unknown", file_type="jsonl")


def test_validation_issue_is_linked_to_sample() -> None:
    sample_id = uuid4()
    issue = ValidationIssue(
        sample_id=sample_id,
        rule="content_nonempty",
        severity="error",
        message="Empty content",
    )

    assert issue.sample_id == sample_id
    assert issue.severity == "error"
