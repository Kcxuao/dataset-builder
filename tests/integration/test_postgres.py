"""Database tests require an isolated PostgreSQL TEST_DATABASE_URL."""

import asyncio
import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select

from dataset_builder.db.orm import ChunkRow, ProjectRow, SourceDocumentRow, TrainingSampleRow
from dataset_builder.db.session import create_engine, create_session_factory


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
