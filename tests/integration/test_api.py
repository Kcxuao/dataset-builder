"""Exercise the HTTP workflow against isolated PostgreSQL storage."""

import asyncio
import json
import os
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dataset_builder.api import create_app
from dataset_builder.db.orm import (
    ChunkRow,
    PipelineRunRow,
    ProjectRow,
    SourceDocumentRow,
    TrainingSampleRow,
    ValidationIssueRow,
)
from dataset_builder.db.session import create_engine, create_session_factory
from dataset_builder.models import Message, PipelineStatus


class FakeLLMClient:
    async def generate(self, messages: list[Message], response_model: type):
        return response_model.model_validate({"pairs": [{"question": "What is this?", "answer": "A test document."}]})


class PausingFakeLLMClient(FakeLLMClient):
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.resume = asyncio.Event()

    async def generate(self, messages: list[Message], response_model: type):
        self.started.set()
        await self.resume.wait()
        return await super().generate(messages, response_model)


@pytest.mark.asyncio
async def test_http_build_review_export(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Set TEST_DATABASE_URL to an isolated PostgreSQL database")
    monkeypatch.setenv("DATABASE_URL", database_url)
    await asyncio.to_thread(command.upgrade, Config("alembic.ini"), "head")
    engine = create_engine(database_url)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            sessions = async_sessionmaker(
                bind=connection, class_=AsyncSession,
                expire_on_commit=False, join_transaction_mode="create_savepoint",
            )
            selected_models: list[str] = []

            def fake_factory(settings):
                selected_models.append(settings.model)
                return FakeLLMClient()

            app = create_app(sessions, tmp_path / "exports", client_factory=fake_factory)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                page = await client.get("/")
                assert page.status_code == 200
                assert "训练数据工作台" in page.text
                assert (await client.get("/static/app.js")).status_code == 200
                assert (await client.get("/api/projects/missing/samples")).status_code == 422
                model = await client.post("/api/models", json={
                    "name": "测试模型", "base_url": "https://example.com/v1", "api_key": "本地测试密钥",
                    "model": "example-model", "concurrency_limit": 2,
                })
                assert model.status_code == 201, model.text
                model_id = model.json()["id"]
                assert "api_key" not in model.json()
                assert "本地测试密钥" not in (await client.get("/api/models")).text
                presets = (await client.get("/api/prompt-presets")).json()
                assert len(presets["qa"]) >= 3
                created = await client.post(
                    "/api/projects/build", files={"file": ("source.txt", b"Test source text")},
                    data={"project_name": "HTTP test", "model_id": model_id,
                          "prompt_preset": "custom", "custom_prompt": "请生成精确问答"},
                )
                assert created.status_code == 202, created.text
                assert selected_models[-1] == "example-model"
                project_id = created.json()["project_id"]
                run_id = created.json()["run_id"]
                async with sessions() as session:
                    run = await session.get(PipelineRunRow, UUID(run_id))
                    assert run.configuration["model_id"] == model_id
                    assert "请生成精确问答" in run.configuration["prompt_text"]
                progress = await client.get(f"/api/runs/{run_id}")
                assert progress.status_code == 200
                assert progress.json()["status"] == "ready_for_review"
                assert progress.json()["total_items"] == 1
                assert progress.json()["completed_items"] == 1
                assert progress.json()["sample_count"] == 1
                projects = (await client.get("/api/projects")).json()
                assert any(project["id"] == project_id and project["sample_count"] == 1 for project in projects)
                samples = (await client.get(f"/api/projects/{project_id}/samples")).json()
                assert len(samples) == 1
                sample_id = samples[0]["id"]
                assert samples[0]["chunk_content"] == "Test source text"
                approved = await client.patch(f"/api/samples/{sample_id}/review", json={"status": "approved"})
                assert approved.status_code == 200
                bulk = await client.patch(f"/api/projects/{project_id}/samples/bulk", json={
                    "sample_ids": [sample_id, str(uuid4())], "action": "pending",
                })
                assert bulk.status_code == 200
                assert bulk.json()["updated_ids"] == [sample_id]
                assert len(bulk.json()["skipped"]) == 1
                bulk = await client.patch(f"/api/projects/{project_id}/samples/bulk", json={
                    "sample_ids": [sample_id], "action": "approved",
                })
                assert bulk.status_code == 200
                for action, expected_deleted in [("delete", True), ("restore", False)]:
                    bulk = await client.patch(f"/api/projects/{project_id}/samples/bulk", json={
                        "sample_ids": [sample_id], "action": action,
                    })
                    assert bulk.status_code == 200
                    assert (await client.get(f"/api/samples/{sample_id}")).json()["is_deleted"] is expected_deleted
                exported = await client.post(
                    f"/api/projects/{project_id}/exports", json={"format": "sharegpt", "file_type": "jsonl"}
                )
                assert exported.status_code == 200, exported.text
                assert exported.json()["sample_count"] == 1
                download = await client.get(exported.json()["download_url"])
                assert download.status_code == 200
                assert len(json.loads(download.text.strip())["conversations"]) == 2
                edited = await client.put(f"/api/samples/{sample_id}/messages", json={"messages": [
                    {"role": "user", "content": "New question"},
                    {"role": "assistant", "content": "New answer"},
                ]})
                assert edited.status_code == 200
                assert edited.json()["review_status"] == "pending"
                invalid = await client.put(f"/api/samples/{sample_id}/messages", json={"messages": [
                    {"role": "user", "content": " "}, {"role": "assistant", "content": "answer"},
                ]})
                assert invalid.json()["validation_status"] == "failed"
                skipped = await client.patch(f"/api/projects/{project_id}/samples/bulk", json={
                    "sample_ids": [sample_id], "action": "approved",
                })
                assert skipped.json()["updated_ids"] == []
                assert len(skipped.json()["skipped"]) == 1
                deleted = await client.patch(f"/api/samples/{sample_id}/deleted", json={"is_deleted": True})
                assert deleted.status_code == 200
                empty = await client.post(
                    f"/api/projects/{project_id}/exports", json={"format": "sharegpt", "file_type": "json"}
                )
                assert empty.status_code == 200
                assert empty.json()["sample_count"] == 0
                malformed = await client.post(
                    "/api/projects/build", files={"file": ("broken.json", b"{")},
                    data={"content_field": "text"},
                )
                assert malformed.status_code == 202
                failed_run = (await client.get(f"/api/runs/{malformed.json()['run_id']}")).json()
                assert failed_run["status"] == "failed"
                assert failed_run["error_message"]
                async with sessions() as session:
                    row = await session.get(PipelineRunRow, UUID(malformed.json()["run_id"]))
                    row.status = PipelineStatus.GENERATING
                    await session.commit()
                interrupted = (await client.get(f"/api/runs/{malformed.json()['run_id']}")).json()
                assert interrupted["status"] == "interrupted"
                no_chunks = await client.post(f"/api/projects/{malformed.json()['project_id']}/retry")
                assert no_chunks.status_code == 422
                assert (await client.get("/api/samples/00000000-0000-0000-0000-000000000000")).status_code == 404
            await transaction.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_run_progress_is_visible_while_model_is_busy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Set TEST_DATABASE_URL to an isolated PostgreSQL database")
    monkeypatch.setenv("DATABASE_URL", database_url)
    await asyncio.to_thread(command.upgrade, Config("alembic.ini"), "head")
    engine = create_engine(database_url)
    sessions = create_session_factory(engine)
    fake = PausingFakeLLMClient()
    app = create_app(sessions, tmp_path / "exports", client_factory=lambda settings: fake)
    name = f"进度测试-{uuid4()}"
    project_id = None
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            building = asyncio.create_task(client.post(
                "/api/projects/build", files={"file": ("slow.txt", b"Slow source")},
                data={"project_name": name},
            ))
            try:
                await asyncio.wait_for(fake.started.wait(), timeout=5)
                projects = (await client.get("/api/projects")).json()
                project = next(item for item in projects if item["name"] == name)
                project_id = UUID(project["id"])
                progress = (await client.get(f"/api/runs/{project['run_id']}")).json()
                assert progress["status"] == "generating"
                assert progress["total_items"] == 1
                assert progress["completed_items"] == 0
                assert progress["sample_count"] == 0
            finally:
                fake.resume.set()
                await asyncio.wait_for(building, timeout=5)
            assert building.result().status_code == 202
            finished = (await client.get(f"/api/runs/{project['run_id']}")).json()
            assert finished["status"] == "ready_for_review"
            assert finished["completed_items"] == 1
            assert finished["sample_count"] == 1
    finally:
        async with sessions() as session:
            if project_id is None:
                project_id = await session.scalar(select(ProjectRow.id).where(ProjectRow.name == name))
            if project_id is not None:
                sample_ids = select(TrainingSampleRow.id).where(TrainingSampleRow.project_id == project_id)
                document_ids = select(SourceDocumentRow.id).where(SourceDocumentRow.project_id == project_id)
                await session.execute(delete(ValidationIssueRow).where(ValidationIssueRow.sample_id.in_(sample_ids)))
                await session.execute(delete(TrainingSampleRow).where(TrainingSampleRow.project_id == project_id))
                await session.execute(delete(ChunkRow).where(ChunkRow.document_id.in_(document_ids)))
                await session.execute(delete(SourceDocumentRow).where(SourceDocumentRow.project_id == project_id))
                await session.execute(delete(PipelineRunRow).where(PipelineRunRow.project_id == project_id))
                await session.execute(delete(ProjectRow).where(ProjectRow.id == project_id))
                await session.commit()
        await engine.dispose()
