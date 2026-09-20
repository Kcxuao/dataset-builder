"""Database tests require an isolated PostgreSQL TEST_DATABASE_URL."""

import asyncio
import json
import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select

from dataset_builder.db.orm import ChunkRow, ExportRecordRow, ProjectRow, SourceDocumentRow, TrainingSampleRow
from dataset_builder.db.session import create_engine, create_session_factory
from dataset_builder.exporters.service import SampleExportService
from dataset_builder.formatters import FormatError
from dataset_builder.models import ExportFileType, ExportFormat


@pytest.mark.asyncio
async def test_migration_and_sample_lineage_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Set TEST_DATABASE_URL to an isolated PostgreSQL database")

    monkeypatch.setenv("DATABASE_URL", database_url)
    await asyncio.to_thread(command.upgrade, Config("alembic.ini"), "head")
    engine = create_engine(database_url)
    factory = create_session_factory(engine)
    project_id, document_id, chunk_id, sample_id = (uuid4() for _ in range(4))
    try:
        async with factory() as session:
            session.add(ProjectRow(id=project_id, name="Integration test"))
            await session.flush()
            session.add(SourceDocumentRow(
                id=document_id, project_id=project_id, source_name="guide.md",
                source_type="markdown", content="Source", metadata_={}, parse_status="success",
            ))
            await session.flush()
            session.add(ChunkRow(
                id=chunk_id, document_id=document_id, index=0, content="Source",
                metadata_={}, generation_status="success",
            ))
            await session.flush()
            session.add(TrainingSampleRow(
                id=sample_id, project_id=project_id, document_id=document_id,
                chunk_id=chunk_id, messages=[{"role": "user", "content": "Question"}],
                metadata_={}, review_status="pending", validation_status="pending",
                is_deleted=False,
            ))
            await session.flush()
            saved = (await session.execute(
                select(TrainingSampleRow).where(TrainingSampleRow.id == sample_id)
            )).scalar_one()
            assert saved.chunk_id == chunk_id
            assert saved.document_id == document_id
            assert saved.messages[0]["role"] == "user"
            await session.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_export_service_streams_only_eligible_samples(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Set TEST_DATABASE_URL to an isolated PostgreSQL database")

    monkeypatch.setenv("DATABASE_URL", database_url)
    await asyncio.to_thread(command.upgrade, Config("alembic.ini"), "head")
    engine = create_engine(database_url)
    factory = create_session_factory(engine)
    project_id, document_id, chunk_id = (uuid4() for _ in range(3))
    try:
        async with factory() as session:
            session.add(ProjectRow(id=project_id, name="Export test"))
            await session.flush()
            session.add(SourceDocumentRow(
                id=document_id, project_id=project_id, source_name="source.md",
                source_type="markdown", content="Source", metadata_={}, parse_status="success",
            ))
            await session.flush()
            session.add(ChunkRow(
                id=chunk_id, document_id=document_id, index=0, content="Source",
                metadata_={}, generation_status="success",
            ))
            await session.flush()
            for review, validation, deleted in [
                ("approved", "passed", False),
                ("pending", "passed", False),
                ("approved", "failed", False),
                ("approved", "passed", True),
            ]:
                session.add(TrainingSampleRow(
                    id=uuid4(), project_id=project_id, document_id=document_id,
                    chunk_id=chunk_id, messages=[
                        {"role": "user", "content": "Q"},
                        {"role": "assistant", "content": "A"},
                    ], metadata_={}, review_status=review,
                    validation_status=validation, is_deleted=deleted,
                ))
            await session.flush()

            destination = tmp_path / "dataset.jsonl"
            record = await SampleExportService(session, batch_size=1).export(
                project_id, ExportFormat.ALPACA, ExportFileType.JSONL, destination
            )

            assert record.status == "completed"
            assert record.sample_count == 1
            assert [json.loads(line) for line in destination.read_text().splitlines()] == [
                {"instruction": "Q", "input": "", "output": "A"}
            ]

            session.add(TrainingSampleRow(
                id=uuid4(), project_id=project_id, document_id=document_id, chunk_id=chunk_id,
                messages=[
                    {"role": "user", "content": "Q1"}, {"role": "assistant", "content": "A1"},
                    {"role": "user", "content": "Q2"}, {"role": "assistant", "content": "A2"},
                ], metadata_={}, review_status="approved", validation_status="passed", is_deleted=False,
            ))
            await session.flush()
            before = destination.read_text()
            with pytest.raises(FormatError):
                await SampleExportService(session, batch_size=1).export(
                    project_id, ExportFormat.ALPACA, ExportFileType.JSONL, destination
                )
            assert destination.read_text() == before
            failed = (await session.execute(
                select(ExportRecordRow).where(
                    ExportRecordRow.project_id == project_id, ExportRecordRow.status == "failed"
                )
            )).scalar_one()
            assert failed.error_message
            await session.rollback()
    finally:
        await engine.dispose()
