"""Exercise the HTTP workflow against isolated PostgreSQL storage."""

import asyncio
import json
import os
from pathlib import Path

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dataset_builder.api import create_app, llm_client
from dataset_builder.db.session import create_engine
from dataset_builder.models import Message


class FakeLLMClient:
    async def generate(self, messages: list[Message], response_model: type):
        return response_model.model_validate({"pairs": [{"question": "What is this?", "answer": "A test document."}]})


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
            app = create_app(sessions, tmp_path / "exports")

            async def fake_client():
                yield FakeLLMClient()

            app.dependency_overrides[llm_client] = fake_client
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                page = await client.get("/")
                assert page.status_code == 200
                assert "训练数据工作台" in page.text
                assert (await client.get("/static/app.js")).status_code == 200
                assert (await client.get("/api/projects/missing/samples")).status_code == 422
                created = await client.post(
                    "/api/projects/build", files={"file": ("source.txt", b"Test source text")},
                    data={"project_name": "HTTP test"},
                )
                assert created.status_code == 200, created.text
                project_id = created.json()["project_id"]
                projects = (await client.get("/api/projects")).json()
                assert any(project["id"] == project_id and project["sample_count"] == 1 for project in projects)
                samples = (await client.get(f"/api/projects/{project_id}/samples")).json()
                assert len(samples) == 1
                sample_id = samples[0]["id"]
                assert samples[0]["chunk_content"] == "Test source text"
                approved = await client.patch(f"/api/samples/{sample_id}/review", json={"status": "approved"})
                assert approved.status_code == 200
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
                deleted = await client.patch(f"/api/samples/{sample_id}/deleted", json={"is_deleted": True})
                assert deleted.status_code == 200
                empty = await client.post(
                    f"/api/projects/{project_id}/exports", json={"format": "sharegpt", "file_type": "json"}
                )
                assert empty.status_code == 200
                assert empty.json()["sample_count"] == 0
                assert (await client.get("/api/samples/00000000-0000-0000-0000-000000000000")).status_code == 404
            await transaction.rollback()
    finally:
        await engine.dispose()
