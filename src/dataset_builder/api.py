"""HTTP entry point for the shared dataset building services."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dataset_builder.application.build import BuildService
from dataset_builder.application.review import ReviewService
from dataset_builder.config import LLMSettings, Settings
from dataset_builder.db.orm import ExportRecordRow, PipelineRunRow, ProjectRow, TrainingSampleRow
from dataset_builder.db.session import create_engine, create_session_factory
from dataset_builder.exporters.service import SampleExportService
from dataset_builder.llm import OpenAICompatibleClient
from dataset_builder.models import ExportFileType, ExportFormat, Message, ReviewStatus


class MessagesPayload(BaseModel):
    messages: list[Message]


class ReviewPayload(BaseModel):
    status: ReviewStatus


class DeletedPayload(BaseModel):
    is_deleted: bool


class ExportPayload(BaseModel):
    format: ExportFormat
    file_type: ExportFileType


def sessions_for(request: Request) -> async_sessionmaker[AsyncSession]:
    return request.app.state.sessions


async def llm_client() -> AsyncIterator[OpenAICompatibleClient]:
    client = OpenAICompatibleClient(LLMSettings())
    try:
        yield client
    finally:
        await client.aclose()


def export_dir_for(request: Request) -> Path:
    return request.app.state.export_dir


def api_error(exc: ValueError | LookupError | OSError) -> HTTPException:
    if isinstance(exc, LookupError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, OSError):
        return HTTPException(status_code=500, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


def create_app(
    sessions: async_sessionmaker[AsyncSession] | None = None,
    export_dir: Path | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if sessions is None:
            settings = Settings()
            engine = create_engine(settings.database_url)
            app.state.sessions = create_session_factory(engine)
            if export_dir is None:
                app.state.export_dir = settings.export_dir
            try:
                yield
            finally:
                await engine.dispose()
        else:
            app.state.sessions = sessions
            yield

    app = FastAPI(title="Dataset Builder", lifespan=lifespan)
    app.state.export_dir = export_dir or Path("exports")
    if sessions is not None:
        app.state.sessions = sessions
    web_dir = Path(__file__).parent / "web"
    app.mount("/static", StaticFiles(directory=web_dir), name="static")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(web_dir / "index.html")

    @app.get("/api/projects")
    async def list_projects(factory: Annotated[async_sessionmaker[AsyncSession], Depends(sessions_for)]) -> list[dict]:
        async with factory() as session:
            query = select(ProjectRow).order_by(ProjectRow.created_at.desc(), ProjectRow.id)
            projects = (await session.scalars(query)).all()
            result = []
            for project in projects:
                run = await session.scalar(
                    select(PipelineRunRow).where(PipelineRunRow.project_id == project.id)
                    .order_by(PipelineRunRow.started_at.desc(), PipelineRunRow.id.desc()).limit(1)
                )
                count = await session.scalar(
                    select(func.count(TrainingSampleRow.id)).where(TrainingSampleRow.project_id == project.id)
                )
                result.append({
                    "id": str(project.id), "name": project.name, "created_at": project.created_at,
                    "sample_count": count, "run_status": run.status if run else None,
                    "failed_chunks": run.failed_items if run else 0,
                })
            return result

    @app.post("/api/projects/build")
    async def build_project(
        file: Annotated[UploadFile, File()],
        factory: Annotated[async_sessionmaker[AsyncSession], Depends(sessions_for)],
        client: Annotated[OpenAICompatibleClient, Depends(llm_client)],
        project_name: Annotated[str | None, Form()] = None,
        generator: Annotated[str, Form()] = "qa",
        splitter: Annotated[str, Form()] = "auto",
        max_chars: Annotated[int, Form(ge=1)] = 1000,
        overlap: Annotated[int, Form(ge=0)] = 0,
        content_field: Annotated[str | None, Form()] = None,
        content_columns: Annotated[str | None, Form()] = None,
    ) -> dict:
        filename = (file.filename or "").replace("\\", "/").split("/")[-1]
        if not filename or filename in {".", ".."}:
            raise HTTPException(status_code=422, detail="A source filename is required")
        with TemporaryDirectory(prefix="dataset-builder-upload-") as directory:
            path = Path(directory) / filename
            with path.open("wb") as destination:
                while data := await file.read(1024 * 1024):
                    destination.write(data)
            try:
                columns = tuple(column.strip() for column in (content_columns or "").split(",") if column.strip())
                summary = await BuildService(factory, client).build(
                    path, project_name or path.stem, generator, splitter, max_chars, overlap,
                    content_field or None, columns,
                )
            except (ValueError, LookupError, OSError) as exc:
                raise api_error(exc) from exc
        return summary.__dict__

    @app.post("/api/projects/{project_id}/retry")
    async def retry_project(
        project_id: UUID,
        factory: Annotated[async_sessionmaker[AsyncSession], Depends(sessions_for)],
        client: Annotated[OpenAICompatibleClient, Depends(llm_client)],
    ) -> dict:
        try:
            summary = await BuildService(factory, client).retry_failed(project_id)
        except (ValueError, LookupError, OSError) as exc:
            raise api_error(exc) from exc
        return summary.__dict__

    @app.get("/api/projects/{project_id}/samples")
    async def list_samples(
        project_id: UUID,
        factory: Annotated[async_sessionmaker[AsyncSession], Depends(sessions_for)],
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> list[dict]:
        async with factory() as session:
            if await session.get(ProjectRow, project_id) is None:
                raise HTTPException(status_code=404, detail="Project does not exist")
            return await ReviewService(session).list_samples(project_id, limit, offset)

    @app.get("/api/samples/{sample_id}")
    async def get_sample(
        sample_id: UUID, factory: Annotated[async_sessionmaker[AsyncSession], Depends(sessions_for)]
    ) -> dict:
        async with factory() as session:
            try:
                return await ReviewService(session).get_sample(sample_id)
            except LookupError as exc:
                raise api_error(exc) from exc

    @app.put("/api/samples/{sample_id}/messages")
    async def edit_sample(
        sample_id: UUID, payload: MessagesPayload,
        factory: Annotated[async_sessionmaker[AsyncSession], Depends(sessions_for)],
    ) -> dict:
        async with factory() as session:
            try:
                result = await ReviewService(session).edit(sample_id, payload.messages)
                await session.commit()
                return result
            except (ValueError, LookupError) as exc:
                raise api_error(exc) from exc

    @app.patch("/api/samples/{sample_id}/review")
    async def review_sample(
        sample_id: UUID, payload: ReviewPayload,
        factory: Annotated[async_sessionmaker[AsyncSession], Depends(sessions_for)],
    ) -> dict:
        async with factory() as session:
            try:
                result = await ReviewService(session).set_review(sample_id, payload.status)
                await session.commit()
                return result
            except (ValueError, LookupError) as exc:
                raise api_error(exc) from exc

    @app.patch("/api/samples/{sample_id}/deleted")
    async def delete_sample(
        sample_id: UUID, payload: DeletedPayload,
        factory: Annotated[async_sessionmaker[AsyncSession], Depends(sessions_for)],
    ) -> dict:
        async with factory() as session:
            try:
                result = await ReviewService(session).set_deleted(sample_id, payload.is_deleted)
                await session.commit()
                return result
            except LookupError as exc:
                raise api_error(exc) from exc

    @app.post("/api/projects/{project_id}/exports")
    async def export_project(
        project_id: UUID, payload: ExportPayload,
        factory: Annotated[async_sessionmaker[AsyncSession], Depends(sessions_for)],
        directory: Annotated[Path, Depends(export_dir_for)],
    ) -> dict:
        async with factory() as session:
            if await session.get(ProjectRow, project_id) is None:
                raise HTTPException(status_code=404, detail="Project does not exist")
            destination = directory.resolve() / f"{project_id}-{uuid4()}.{payload.file_type.value}"
            try:
                record = await SampleExportService(session).export(
                    project_id, payload.format, payload.file_type, destination
                )
            except (ValueError, OSError) as exc:
                await session.commit()
                raise api_error(exc) from exc
            await session.commit()
            return {**record.model_dump(mode="json"), "download_url": f"/api/exports/{record.id}/download"}

    @app.get("/api/exports/{export_id}/download")
    async def download_export(
        export_id: UUID,
        factory: Annotated[async_sessionmaker[AsyncSession], Depends(sessions_for)],
        directory: Annotated[Path, Depends(export_dir_for)],
    ) -> FileResponse:
        async with factory() as session:
            record = await session.get(ExportRecordRow, export_id)
            if record is None or record.status != "completed" or not record.file_path:
                raise HTTPException(status_code=404, detail="Export does not exist")
            path = Path(record.file_path).resolve()
            if not path.is_relative_to(directory.resolve()) or not path.is_file():
                raise HTTPException(status_code=404, detail="Export file is unavailable")
            return FileResponse(path, filename=f"dataset-{record.format}.{record.file_type}")

    return app


app = create_app()
