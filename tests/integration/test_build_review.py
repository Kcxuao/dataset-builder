"""A full local flow with Fake LLM responses and real PostgreSQL storage."""

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dataset_builder.application.build import BuildService
from dataset_builder.application.review import ReviewService
from dataset_builder.db.orm import ChunkRow, PipelineRunRow, SourceDocumentRow, TrainingSampleRow
from dataset_builder.db.session import create_engine
from dataset_builder.exporters.service import SampleExportService
from dataset_builder.generators.qa import QAResponse
from dataset_builder.models import ExportFileType, ExportFormat, Message, ReviewStatus


class FakeLLMClient:
    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, messages: list[Message], response_model: type[QAResponse]) -> QAResponse:
        self.calls += 1
        if self.calls == 2:
            raise RuntimeError("simulated chunk failure")
        return response_model.model_validate({"pairs": [{"question": "What?", "answer": "Answer"}]})


class MappingFakeLLMClient:
    async def generate(self, messages: list[Message], response_model: type[QAResponse]) -> QAResponse:
        content = messages[-1].content
        return response_model.model_validate({"pairs": [{"question": f"What is {content}?", "answer": content}]})


class ConcurrentFakeLLMClient:
    def __init__(self) -> None:
        self.settings = SimpleNamespace(
            base_url="fake", model="fake", temperature=0, max_tokens=100, concurrency_limit=3,
        )
        self.active = 0
        self.peak = 0

    async def generate(self, messages: list[Message], response_model: type[QAResponse]) -> QAResponse:
        self.active += 1
        self.peak = max(self.peak, self.active)
        await asyncio.sleep(0.02)
        self.active -= 1
        content = messages[-1].content
        return response_model.model_validate({"pairs": [{"question": f"What is {content}?", "answer": content}]})


@pytest.mark.asyncio
async def test_build_review_and_export_flow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Set TEST_DATABASE_URL to an isolated PostgreSQL database")
    monkeypatch.setenv("DATABASE_URL", database_url)
    await asyncio.to_thread(command.upgrade, Config("alembic.ini"), "head")
    source = tmp_path / "source.txt"
    source.write_text("abcdefgh", encoding="utf-8")
    engine = create_engine(database_url)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            sessions = async_sessionmaker(
                bind=connection, class_=AsyncSession,
                expire_on_commit=False, join_transaction_mode="create_savepoint",
            )
            try:
                fake = FakeLLMClient()
                summary = await BuildService(sessions, fake).build(
                    source, "Test project", max_chunk_length=4, splitter_mode="fixed"
                )
                assert summary.document_count == 1
                assert summary.chunk_count == 2
                assert summary.sample_count == 1
                assert summary.failed_chunk_count == 1

                async with sessions() as session:
                    run = await session.get(PipelineRunRow, summary.run_id)
                    chunks = (await session.scalars(
                        select(ChunkRow)
                        .join(SourceDocumentRow)
                        .where(SourceDocumentRow.project_id == summary.project_id)
                    )).all()
                    assert run.status == "ready_for_review"
                    assert sorted(chunk.generation_status for chunk in chunks) == ["failed", "success"]

                    review = ReviewService(session)
                    listed = await review.list_samples(summary.project_id)
                    assert len(listed) == 1
                    sample_id = UUID(listed[0]["id"])
                    assert listed[0]["chunk_content"] == "abcd"
                    original_hash = (await session.get(TrainingSampleRow, sample_id)).content_hash
                    invalid = await review.edit(sample_id, [
                        Message(role="user", content=" "), Message(role="assistant", content="A"),
                    ])
                    assert invalid["validation_status"] == "failed"
                    assert any(issue["rule"] == "empty_content" for issue in invalid["issues"])
                    with pytest.raises(ValueError, match="validated"):
                        await review.set_review(sample_id, ReviewStatus.APPROVED)
                    edited = await review.edit(sample_id, [
                        Message(role="user", content=" New question "),
                        Message(role="assistant", content=" New answer "),
                    ])
                    assert edited["messages"][0]["content"] == "New question"
                    assert edited["review_status"] == "pending"
                    assert (await session.get(TrainingSampleRow, sample_id)).content_hash != original_hash
                    approved = await review.set_review(sample_id, ReviewStatus.APPROVED)
                    assert approved["review_status"] == "approved"
                    await review.set_deleted(sample_id, True)
                    await session.flush()
                    empty_file = tmp_path / "empty.jsonl"
                    empty = await SampleExportService(session).export(
                        summary.project_id, ExportFormat.ALPACA, ExportFileType.JSONL, empty_file
                    )
                    assert empty.sample_count == 0
                    await review.set_deleted(sample_id, False)
                    output = tmp_path / "dataset.jsonl"
                    exported = await SampleExportService(session).export(
                        summary.project_id, ExportFormat.ALPACA, ExportFileType.JSONL, output
                    )
                    assert exported.sample_count == 1
                    assert "New question" in output.read_text(encoding="utf-8")
                    await session.rollback()

                retried = await BuildService(sessions, fake).retry_failed(summary.project_id)
                assert retried.chunk_count == 1
                assert retried.sample_count == 1
                assert retried.failed_chunk_count == 0
                assert fake.calls == 3
                async with sessions() as session:
                    run = await session.get(PipelineRunRow, summary.run_id)
                    assert run.completed_items == 2
                    assert run.failed_items == 0
                    assert len(await ReviewService(session).list_samples(summary.project_id)) == 2
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("filename,contents,mapping", [
    ("records.json", '[{"body":"One"},{"body":"Two"}]', {"content_field": "body"}),
    ("records.jsonl", '{"body":"One"}\n{"body":"Two"}\n', {"content_field": "body"}),
    ("records.csv", "body,ignored\nOne,x\nTwo,y\n", {"content_columns": ("body",)}),
])
async def test_structured_file_build_flow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, filename: str, contents: str, mapping: dict
) -> None:
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Set TEST_DATABASE_URL to an isolated PostgreSQL database")
    monkeypatch.setenv("DATABASE_URL", database_url)
    await asyncio.to_thread(command.upgrade, Config("alembic.ini"), "head")
    source = tmp_path / filename
    source.write_text(contents, encoding="utf-8")
    engine = create_engine(database_url)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            sessions = async_sessionmaker(
                bind=connection, class_=AsyncSession,
                expire_on_commit=False, join_transaction_mode="create_savepoint",
            )
            try:
                summary = await BuildService(sessions, MappingFakeLLMClient()).build(
                    source, "Mapped import", parser_workers=4, **mapping
                )
                assert summary.document_count == 2
                assert summary.chunk_count == 2
                assert summary.sample_count == 2
                assert summary.failed_chunk_count == 0
                async with sessions() as session:
                    listed = await ReviewService(session).list_samples(summary.project_id)
                    assert len(listed) == 2
                    assert {item["chunk_content"] for item in listed} == (
                        {"body: One", "body: Two"} if filename.endswith(".csv") else {"One", "Two"}
                    )
                    assert len({item["metadata"]["record_index"] for item in listed}) == 2
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_build_generates_chunks_concurrently(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Set TEST_DATABASE_URL to an isolated PostgreSQL database")
    monkeypatch.setenv("DATABASE_URL", database_url)
    await asyncio.to_thread(command.upgrade, Config("alembic.ini"), "head")
    source = tmp_path / "source.txt"
    source.write_text("abcdefghijkl", encoding="utf-8")
    engine = create_engine(database_url)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            sessions = async_sessionmaker(
                bind=connection, class_=AsyncSession,
                expire_on_commit=False, join_transaction_mode="create_savepoint",
            )
            try:
                fake = ConcurrentFakeLLMClient()
                summary = await BuildService(sessions, fake).build(
                    source, "Concurrent build", splitter_mode="fixed", max_chunk_length=3,
                )
                assert fake.peak == 3
                assert summary.chunk_count == 4
                assert summary.sample_count == 4
                assert summary.failed_chunk_count == 0
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()
