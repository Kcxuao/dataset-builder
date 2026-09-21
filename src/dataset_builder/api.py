"""HTTP entry point for the shared dataset building services."""

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dataset_builder.application.build import BuildService
from dataset_builder.application.model_configs import ModelConfigInput, ModelConfigService
from dataset_builder.application.model_discovery import (
    ModelCatalogFactory,
    ModelConnectionCheckInput,
    ModelConnectionService,
    ModelDiscoveryInput,
    ModelDiscoveryService,
    list_model_providers,
)
from dataset_builder.application.projects import ProjectService
from dataset_builder.application.review import ReviewService
from dataset_builder.application.workspace import PromptTemplateInput, WorkspaceService, WorkspaceSettingsInput
from dataset_builder.config import LLMSettings, Settings
from dataset_builder.db.orm import (
    ChunkRow,
    ExportRecordRow,
    PipelineRunRow,
    ProjectRow,
    SourceDocumentRow,
    TrainingSampleRow,
)
from dataset_builder.db.session import create_engine, create_session_factory
from dataset_builder.exporters.service import SampleExportService
from dataset_builder.generators.prompts import list_prompt_presets
from dataset_builder.llm import OpenAICompatibleClient, OpenAICompatibleModelCatalog
from dataset_builder.models import ExportFileType, ExportFormat, Message, PipelineStatus, ReviewStatus, utc_now

logger = logging.getLogger(__name__)
ACTIVE_STATUSES = {
    PipelineStatus.CREATED, PipelineStatus.IMPORTING, PipelineStatus.PARSING,
    PipelineStatus.SPLITTING, PipelineStatus.GENERATING, PipelineStatus.CLEANING,
    PipelineStatus.VALIDATING,
}


class MessagesPayload(BaseModel):
    messages: list[Message]


class ReviewPayload(BaseModel):
    status: ReviewStatus


class DeletedPayload(BaseModel):
    is_deleted: bool


class BulkPayload(BaseModel):
    sample_ids: list[UUID] = Field(min_length=1, max_length=200)
    action: Literal["approved", "rejected", "pending", "delete", "restore"]


class ExportPayload(BaseModel):
    format: ExportFormat
    file_type: ExportFileType


def upload_filename(file: UploadFile) -> str:
    filename = (file.filename or "").replace("\\", "/").split("/")[-1]
    if not filename or filename in {".", ".."}:
        raise HTTPException(status_code=422, detail="必须提供源文件名")
    return filename


async def save_upload(file: UploadFile, temporary: TemporaryDirectory[str], filename: str) -> Path:
    path = Path(temporary.name) / filename
    with path.open("wb") as destination:
        while data := await file.read(1024 * 1024):
            destination.write(data)
    return path


def sessions_for(request: Request) -> async_sessionmaker[AsyncSession]:
    return request.app.state.sessions


async def selected_client(
    factory: async_sessionmaker[AsyncSession], model_id: UUID | None,
    client_factory: Callable[[LLMSettings], object],
) -> object:
    if model_id is None:
        try:
            settings = LLMSettings()
        except ValidationError as exc:
            fields = ", ".join(sorted({"LLM_" + str(error["loc"][0]).upper() for error in exc.errors()}))
            raise HTTPException(status_code=503, detail=f"模型配置缺失或无效：{fields}") from exc
    else:
        async with factory() as session:
            try:
                settings = await ModelConfigService(session).settings_for(model_id)
            except LookupError as exc:
                raise api_error(exc) from exc
    return client_factory(settings)


async def close_client(client: object) -> None:
    close = getattr(client, "aclose", None)
    if close is not None:
        await close()


async def run_build_in_background(
    factory: async_sessionmaker[AsyncSession], client: object, run_id: UUID,
    path: Path, temporary: TemporaryDirectory[str], app: FastAPI,
) -> None:
    try:
        await BuildService(factory, client).execute_build(run_id, path)
    except Exception:
        logger.error("后台构建失败：运行编号 %s，详情已写入任务记录", run_id)
    finally:
        try:
            await close_client(client)
        finally:
            temporary.cleanup()
            app.state.active_run_ids.discard(run_id)


async def run_retry_in_background(
    factory: async_sessionmaker[AsyncSession], client: object, project_id: UUID, run_id: UUID, app: FastAPI,
) -> None:
    try:
        await BuildService(factory, client).retry_failed(project_id)
    except Exception as exc:
        async with factory() as session:
            run = await session.get(PipelineRunRow, run_id)
            if run is not None:
                run.status = PipelineStatus.FAILED
                run.error_message = f"{type(exc).__name__}: {exc}"[:500]
                run.finished_at = utc_now()
                await session.commit()
        logger.error("后台重试失败：运行编号 %s，详情已写入任务记录", run_id)
    finally:
        try:
            await close_client(client)
        finally:
            app.state.active_run_ids.discard(run_id)


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
    client_factory: Callable[[LLMSettings], object] = OpenAICompatibleClient,
    model_catalog_factory: ModelCatalogFactory = OpenAICompatibleModelCatalog,
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
    app.state.active_run_ids = set()
    app.state.client_factory = client_factory
    app.state.model_catalog_factory = model_catalog_factory
    project_logger = logging.getLogger("dataset_builder")
    project_logger.setLevel(logging.INFO)
    if not project_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        project_logger.addHandler(handler)
    project_logger.propagate = False
    app.state.export_dir = export_dir or Path("exports")
    if sessions is not None:
        app.state.sessions = sessions
    web_dir = Path(__file__).parent / "web"
    app.mount("/static", StaticFiles(directory=web_dir), name="static")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(web_dir / "index.html")

    @app.get("/api/projects")
    async def list_projects(
        factory: Annotated[async_sessionmaker[AsyncSession], Depends(sessions_for)],
        trash: bool = False,
    ) -> list[dict]:
        async with factory() as session:
            query = select(ProjectRow).where(
                ProjectRow.deleted_at.is_not(None) if trash else ProjectRow.deleted_at.is_(None)
            ).order_by(ProjectRow.created_at.desc(), ProjectRow.id)
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
                    "run_id": str(run.id) if run else None,
                    "deleted_at": project.deleted_at,
                })
            return result

    @app.delete("/api/projects/{project_id}")
    async def trash_project(
        project_id: UUID, request: Request,
        factory: Annotated[async_sessionmaker[AsyncSession], Depends(sessions_for)],
    ) -> dict:
        async with factory() as session:
            try:
                await ProjectService(session).get_active(project_id)
            except LookupError as exc:
                raise api_error(exc) from exc
            active = await session.scalar(select(PipelineRunRow.id).where(
                PipelineRunRow.project_id == project_id,
                PipelineRunRow.id.in_(request.app.state.active_run_ids),
            ).limit(1)) if request.app.state.active_run_ids else None
            if active:
                raise HTTPException(status_code=409, detail="构建任务运行中，暂不能删除数据集")
            await ProjectService(session).move_to_trash(project_id)
            await session.commit()
            return {"id": str(project_id), "deleted": True}

    @app.post("/api/projects/{project_id}/restore")
    async def restore_project(
        project_id: UUID, factory: Annotated[async_sessionmaker[AsyncSession], Depends(sessions_for)]
    ) -> dict:
        async with factory() as session:
            try:
                await ProjectService(session).restore(project_id)
            except LookupError as exc:
                raise api_error(exc) from exc
            await session.commit()
            return {"id": str(project_id), "deleted": False}

    @app.get("/api/models")
    async def list_models(factory: Annotated[async_sessionmaker[AsyncSession], Depends(sessions_for)]) -> list[dict]:
        async with factory() as session:
            return await ModelConfigService(session).list_models()

    @app.get("/api/model-providers")
    async def list_providers() -> list[dict[str, str | None]]:
        return list_model_providers()

    @app.post("/api/models/discover")
    async def discover_models(
        payload: ModelDiscoveryInput,
        request: Request,
        factory: Annotated[async_sessionmaker[AsyncSession], Depends(sessions_for)],
    ) -> dict[str, list[dict[str, str]]]:
        async with factory() as session:
            try:
                return await ModelDiscoveryService(
                    session, request.app.state.model_catalog_factory,
                ).discover(payload)
            except (ValueError, LookupError) as exc:
                raise api_error(exc) from exc

    @app.post("/api/models/connection-check")
    async def check_model_connections(
        payload: ModelConnectionCheckInput,
        request: Request,
        factory: Annotated[async_sessionmaker[AsyncSession], Depends(sessions_for)],
    ) -> dict[str, list[dict[str, object]]]:
        async with factory() as session:
            return await ModelConnectionService(
                session, request.app.state.model_catalog_factory,
            ).check(payload)

    @app.post("/api/models", status_code=201)
    async def create_model(
        payload: ModelConfigInput, factory: Annotated[async_sessionmaker[AsyncSession], Depends(sessions_for)]
    ) -> dict:
        async with factory() as session:
            try:
                result = await ModelConfigService(session).create(payload)
                await session.commit()
                return result
            except ValueError as exc:
                raise api_error(exc) from exc

    @app.put("/api/models/{model_id}")
    async def update_model(
        model_id: UUID, payload: ModelConfigInput,
        factory: Annotated[async_sessionmaker[AsyncSession], Depends(sessions_for)],
    ) -> dict:
        async with factory() as session:
            try:
                result = await ModelConfigService(session).update(model_id, payload)
                await session.commit()
                return result
            except (ValueError, LookupError) as exc:
                raise api_error(exc) from exc

    @app.delete("/api/models/{model_id}", status_code=204)
    async def archive_model(
        model_id: UUID, factory: Annotated[async_sessionmaker[AsyncSession], Depends(sessions_for)]
    ) -> None:
        async with factory() as session:
            try:
                await ModelConfigService(session).archive(model_id)
                await session.commit()
            except LookupError as exc:
                raise api_error(exc) from exc

    @app.get("/api/workspace/settings")
    async def get_workspace_settings(
        factory: Annotated[async_sessionmaker[AsyncSession], Depends(sessions_for)]
    ) -> dict:
        async with factory() as session:
            return await WorkspaceService(session).settings()

    @app.put("/api/workspace/settings")
    async def update_workspace_settings(
        payload: WorkspaceSettingsInput,
        factory: Annotated[async_sessionmaker[AsyncSession], Depends(sessions_for)],
    ) -> dict:
        async with factory() as session:
            try:
                result = await WorkspaceService(session).save_settings(payload)
                await session.commit()
                return result
            except ValueError as exc:
                raise api_error(exc) from exc

    @app.get("/api/prompts")
    async def list_prompts(factory: Annotated[async_sessionmaker[AsyncSession], Depends(sessions_for)]) -> list[dict]:
        async with factory() as session:
            return await WorkspaceService(session).list_prompts()

    @app.post("/api/prompts", status_code=201)
    async def create_prompt(
        payload: PromptTemplateInput, factory: Annotated[async_sessionmaker[AsyncSession], Depends(sessions_for)]
    ) -> dict:
        async with factory() as session:
            try:
                result = await WorkspaceService(session).create_prompt(payload)
                await session.commit()
                return result
            except ValueError as exc:
                raise api_error(exc) from exc

    @app.put("/api/prompts/{prompt_id}")
    async def update_prompt(
        prompt_id: UUID, payload: PromptTemplateInput,
        factory: Annotated[async_sessionmaker[AsyncSession], Depends(sessions_for)],
    ) -> dict:
        async with factory() as session:
            try:
                result = await WorkspaceService(session).update_prompt(prompt_id, payload)
                await session.commit()
                return result
            except (ValueError, LookupError) as exc:
                raise api_error(exc) from exc

    @app.delete("/api/prompts/{prompt_id}", status_code=204)
    async def delete_prompt(
        prompt_id: UUID, factory: Annotated[async_sessionmaker[AsyncSession], Depends(sessions_for)]
    ) -> None:
        async with factory() as session:
            try:
                await WorkspaceService(session).delete_prompt(prompt_id)
                await session.commit()
            except LookupError as exc:
                raise api_error(exc) from exc

    @app.get("/api/prompt-presets")
    async def prompt_presets() -> dict[str, list[dict[str, str]]]:
        return list_prompt_presets()

    @app.post("/api/projects/build", status_code=202)
    async def build_project(
        file: Annotated[UploadFile, File()],
        background_tasks: BackgroundTasks,
        request: Request,
        factory: Annotated[async_sessionmaker[AsyncSession], Depends(sessions_for)],
        project_name: Annotated[str | None, Form()] = None,
        generator: Annotated[str, Form()] = "qa",
        splitter: Annotated[str, Form()] = "auto",
        max_chars: Annotated[int, Form(ge=1)] = 1000,
        overlap: Annotated[int, Form(ge=0)] = 0,
        parser_workers: Annotated[int | None, Form(ge=1, le=16)] = None,
        content_field: Annotated[str | None, Form()] = None,
        content_columns: Annotated[str | None, Form()] = None,
        model_id: Annotated[UUID | None, Form()] = None,
        prompt_preset: Annotated[str, Form()] = "default",
        custom_prompt: Annotated[str | None, Form()] = None,
        prompt_id: Annotated[str | None, Form()] = None,
    ) -> dict:
        filename = upload_filename(file)
        async with factory() as session:
            workspace = WorkspaceService(session)
            defaults = await workspace.settings()
            if model_id is None and defaults["default_model_id"]:
                model_id = UUID(str(defaults["default_model_id"]))
            if model_id is not None:
                try:
                    await ModelConfigService(session).active_model(model_id)
                except LookupError as exc:
                    raise api_error(exc) from exc
            parser_workers = parser_workers or int(defaults["parser_workers"])
            if prompt_id:
                try:
                    prompt_preset, custom_prompt = await workspace.resolve_prompt(generator, prompt_id)
                except ValueError as exc:
                    raise api_error(exc) from exc
        client = await selected_client(factory, model_id, request.app.state.client_factory)
        temporary = TemporaryDirectory(prefix="dataset-builder-upload-")
        try:
            path = await save_upload(file, temporary, filename)
            columns = tuple(column.strip() for column in (content_columns or "").split(",") if column.strip())
            summary = await BuildService(factory, client).prepare_build(
                path, project_name or path.stem, generator, splitter, max_chars, overlap,
                content_field or None, columns, entrypoint="web", parser_workers=parser_workers,
                prompt_preset=prompt_preset, custom_prompt=custom_prompt, model_id=model_id,
            )
        except Exception as exc:
            temporary.cleanup()
            await close_client(client)
            if isinstance(exc, (ValueError, LookupError, OSError)):
                raise api_error(exc) from exc
            raise
        request.app.state.active_run_ids.add(summary.run_id)
        background_tasks.add_task(
            run_build_in_background, factory, client, summary.run_id, path, temporary, request.app
        )
        return {"project_id": summary.project_id, "run_id": summary.run_id}

    @app.post("/api/projects/preview")
    async def preview_project(
        file: Annotated[UploadFile, File()],
        factory: Annotated[async_sessionmaker[AsyncSession], Depends(sessions_for)],
        generator: Annotated[str, Form()] = "qa",
        splitter: Annotated[str, Form()] = "auto",
        max_chars: Annotated[int, Form(ge=1)] = 1000,
        overlap: Annotated[int, Form(ge=0)] = 0,
        parser_workers: Annotated[int | None, Form(ge=1, le=16)] = None,
        content_field: Annotated[str | None, Form()] = None,
        content_columns: Annotated[str | None, Form()] = None,
        model_id: Annotated[UUID | None, Form()] = None,
        prompt_preset: Annotated[str, Form()] = "default",
        custom_prompt: Annotated[str | None, Form()] = None,
        prompt_id: Annotated[str | None, Form()] = None,
    ) -> dict:
        filename = upload_filename(file)
        async with factory() as session:
            workspace = WorkspaceService(session)
            defaults = await workspace.settings()
            parser_workers = parser_workers or int(defaults["parser_workers"])
            if model_id is None and defaults["default_model_id"]:
                model_id = UUID(str(defaults["default_model_id"]))
            if model_id is not None:
                try:
                    await ModelConfigService(session).active_model(model_id)
                except LookupError as exc:
                    raise api_error(exc) from exc
            if prompt_id:
                try:
                    prompt_preset, custom_prompt = await workspace.resolve_prompt(generator, prompt_id)
                except ValueError as exc:
                    raise api_error(exc) from exc
        temporary = TemporaryDirectory(prefix="dataset-builder-preview-")
        try:
            path = await save_upload(file, temporary, filename)
            columns = tuple(column.strip() for column in (content_columns or "").split(",") if column.strip())
            preview = await BuildService(factory, None).preview(
                path, generator, splitter, max_chars, overlap, content_field or None, columns,
                parser_workers, custom_prompt, model_id,
            )
            max_output_tokens = None
            if model_id is not None:
                async with factory() as session:
                    max_output_tokens = (await ModelConfigService(session).settings_for(model_id)).max_tokens
            return {
                "fingerprint": preview.fingerprint, "document_count": len(preview.documents),
                "chunk_count": len(preview.chunks), "estimated_request_upper_bound": len(preview.chunks),
                "max_output_tokens": max_output_tokens,
                "chunks": [
                    {
                        "index": index, "content": chunk.content, "length": len(chunk.content),
                        "source_name": next(
                            document.source_name for document in preview.documents if document.id == chunk.document_id
                        ),
                    }
                    for index, chunk in enumerate(preview.chunks[:20])
                ],
            }
        except (ValueError, LookupError, OSError) as exc:
            raise api_error(exc) from exc
        finally:
            temporary.cleanup()

    @app.post("/api/projects/preview/generate")
    async def generate_preview(
        file: Annotated[UploadFile, File()], request: Request,
        factory: Annotated[async_sessionmaker[AsyncSession], Depends(sessions_for)],
        fingerprint: Annotated[str, Form(min_length=1)], chunk_indices: Annotated[str, Form(min_length=1)],
        generator: Annotated[str, Form()] = "qa", splitter: Annotated[str, Form()] = "auto",
        max_chars: Annotated[int, Form(ge=1)] = 1000, overlap: Annotated[int, Form(ge=0)] = 0,
        parser_workers: Annotated[int | None, Form(ge=1, le=16)] = None,
        content_field: Annotated[str | None, Form()] = None, content_columns: Annotated[str | None, Form()] = None,
        model_id: Annotated[UUID | None, Form()] = None, prompt_preset: Annotated[str, Form()] = "default",
        custom_prompt: Annotated[str | None, Form()] = None, prompt_id: Annotated[str | None, Form()] = None,
    ) -> dict:
        filename = upload_filename(file)
        try:
            indices = [int(value) for value in chunk_indices.split(",") if value.strip()]
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="试生成内容块序号必须是整数") from exc
        async with factory() as session:
            workspace = WorkspaceService(session)
            defaults = await workspace.settings()
            parser_workers = parser_workers or int(defaults["parser_workers"])
            if model_id is None and defaults["default_model_id"]:
                model_id = UUID(str(defaults["default_model_id"]))
            if model_id is not None:
                try:
                    await ModelConfigService(session).active_model(model_id)
                except LookupError as exc:
                    raise api_error(exc) from exc
            if prompt_id:
                try:
                    prompt_preset, custom_prompt = await workspace.resolve_prompt(generator, prompt_id)
                except ValueError as exc:
                    raise api_error(exc) from exc
        client = await selected_client(factory, model_id, request.app.state.client_factory)
        temporary = TemporaryDirectory(prefix="dataset-builder-preview-")
        try:
            path = await save_upload(file, temporary, filename)
            columns = tuple(column.strip() for column in (content_columns or "").split(",") if column.strip())
            samples, issues = await BuildService(factory, client).generate_preview(
                path, indices, fingerprint, generator, splitter, max_chars, overlap, content_field or None,
                columns, parser_workers, custom_prompt, model_id,
            )
            return {
                "samples": [sample.model_dump(mode="json") for sample in samples],
                "issues": [issue.model_dump(mode="json") for issue in issues],
            }
        except (ValueError, LookupError, OSError) as exc:
            raise api_error(exc) from exc
        finally:
            temporary.cleanup()
            await close_client(client)

    @app.post("/api/projects/{project_id}/retry", status_code=202)
    async def retry_project(
        project_id: UUID,
        background_tasks: BackgroundTasks,
        request: Request,
        factory: Annotated[async_sessionmaker[AsyncSession], Depends(sessions_for)],
    ) -> dict:
        async with factory() as session:
            try:
                await ProjectService(session).get_active(project_id)
            except LookupError as exc:
                raise api_error(exc) from exc
            run = await session.scalar(
                select(PipelineRunRow).where(PipelineRunRow.project_id == project_id)
                .order_by(PipelineRunRow.started_at.desc(), PipelineRunRow.id.desc()).limit(1)
            )
            if run is None:
                raise HTTPException(status_code=404, detail="项目没有构建记录")
            if run.id in request.app.state.active_run_ids:
                raise HTTPException(status_code=409, detail="构建任务仍在执行")
            if run.status in ACTIVE_STATUSES and run.configuration.get("entrypoint") == "web" and not run.total_items:
                raise HTTPException(status_code=422, detail="任务在切分完成前中断，请重新上传文件")
            model_id = UUID(run.configuration["model_id"]) if run.configuration.get("model_id") else None
            client = await selected_client(factory, model_id, request.app.state.client_factory)
            if run.configuration.get("llm") != BuildService(factory, client)._llm_signature():
                await close_client(client)
                raise HTTPException(status_code=422, detail="当前模型配置与原构建任务不一致")
            run_id = run.id
            run.status = PipelineStatus.GENERATING
            run.current_stage = PipelineStatus.GENERATING
            run.finished_at = None
            run.error_message = None
            await session.commit()
        request.app.state.active_run_ids.add(run_id)
        background_tasks.add_task(run_retry_in_background, factory, client, project_id, run_id, request.app)
        return {"project_id": project_id, "run_id": run_id}

    @app.get("/api/runs/{run_id}")
    async def get_run(
        run_id: UUID, request: Request,
        factory: Annotated[async_sessionmaker[AsyncSession], Depends(sessions_for)],
    ) -> dict:
        async with factory() as session:
            run = await session.get(PipelineRunRow, run_id)
            if run is None:
                raise HTTPException(status_code=404, detail="构建任务不存在")
            try:
                await ProjectService(session).get_active(run.project_id)
            except LookupError as exc:
                raise api_error(exc) from exc
            interrupted = (
                run.status in ACTIVE_STATUSES and run.configuration.get("entrypoint") == "web"
                and run.id not in request.app.state.active_run_ids
            )
            failed = (await session.scalars(
                select(ChunkRow).join(SourceDocumentRow)
                .where(SourceDocumentRow.project_id == run.project_id, ChunkRow.generation_status == "failed")
                .order_by(ChunkRow.created_at, ChunkRow.id).limit(20)
            )).all()
            sample_count = await session.scalar(
                select(func.count(TrainingSampleRow.id)).where(TrainingSampleRow.project_id == run.project_id)
            )
            return {
                "id": str(run.id), "project_id": str(run.project_id),
                "status": "interrupted" if interrupted else run.status,
                "current_stage": run.current_stage,
                "total_items": run.total_items, "completed_items": run.completed_items,
                "failed_items": run.failed_items, "sample_count": sample_count,
                "error_message": run.error_message,
                "started_at": run.started_at, "finished_at": run.finished_at,
                "failed_chunks": [
                    {"id": str(chunk.id), "error": chunk.metadata_.get("generation_error", "生成失败")}
                    for chunk in failed
                ],
            }

    @app.get("/api/projects/{project_id}/samples")
    async def list_samples(
        project_id: UUID,
        factory: Annotated[async_sessionmaker[AsyncSession], Depends(sessions_for)],
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> list[dict]:
        async with factory() as session:
            try:
                await ProjectService(session).get_active(project_id)
            except LookupError as exc:
                raise api_error(exc) from exc
            return await ReviewService(session).list_samples(project_id, limit, offset)

    @app.patch("/api/projects/{project_id}/samples/bulk")
    async def bulk_samples(
        project_id: UUID, payload: BulkPayload,
        factory: Annotated[async_sessionmaker[AsyncSession], Depends(sessions_for)],
    ) -> dict:
        async with factory() as session:
            try:
                await ProjectService(session).get_active(project_id)
            except LookupError as exc:
                raise api_error(exc) from exc
            result = await ReviewService(session).bulk_action(project_id, payload.sample_ids, payload.action)
            await session.commit()
            return result

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
            try:
                await ProjectService(session).get_active(project_id)
            except LookupError as exc:
                raise api_error(exc) from exc
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
                raise HTTPException(status_code=404, detail="导出记录不存在")
            try:
                await ProjectService(session).get_active(record.project_id)
            except LookupError as exc:
                raise api_error(exc) from exc
            path = Path(record.file_path).resolve()
            if not path.is_relative_to(directory.resolve()) or not path.is_file():
                raise HTTPException(status_code=404, detail="导出文件不可用")
            return FileResponse(path, filename=f"dataset-{record.format}.{record.file_type}")

    return app


app = create_app()
