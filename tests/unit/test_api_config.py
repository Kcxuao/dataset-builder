"""Missing LLM settings should produce a useful API response."""

from pathlib import Path

import httpx
import pytest

from dataset_builder.api import create_app, sessions_for


@pytest.mark.asyncio
async def test_build_reports_missing_llm_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    app = create_app(export_dir=tmp_path)
    app.dependency_overrides[sessions_for] = lambda: None
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/projects/build", files={"file": ("source.txt", b"text")})
    assert response.status_code == 503
    assert "LLM_BASE_URL" in response.json()["detail"]
    assert "LLM_MODEL" in response.json()["detail"]
