"""Upgrade approved answers with a teacher model while retaining source lineage."""

import hashlib
import json
from dataclasses import dataclass
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Text, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dataset_builder.cleaners import BasicCleaner
from dataset_builder.db.orm import (
    ChunkRow,
    DistillationJobRow,
    PipelineRunRow,
    ProjectRow,
    TrainingSampleRow,
)
from dataset_builder.llm import LLMClient, QuotaExceededError
from dataset_builder.models import Message, MessageRole, PipelineStatus, TrainingSample, utc_now
from dataset_builder.validators import SampleValidator


class DistillationResponse(BaseModel):
    assistant_messages: list[str] = Field(min_length=1)

    @field_validator("assistant_messages")
    @classmethod
    def nonblank(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values]
        if any(not value for value in cleaned):
            raise ValueError("assistant_messages 不能包含空回复")
        return cleaned


@dataclass(frozen=True)
class DistillationOptions:
    target_count: int
    keyword: str | None
    source_document_ids: tuple[UUID, ...]
    prompt_text: str
    model_id: UUID | None


@dataclass(frozen=True)
class DistillationPreview:
    eligible_count: int
    target_count: int
    fingerprint: str


class DistillationService:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], client: LLMClient) -> None:
        self.sessions = sessions
        self.client = client
        self.cleaner = BasicCleaner()
        self.validator = SampleValidator()

    @staticmethod
    def validate_options(target_count: int) -> int:
        if not 1 <= target_count <= 1000:
            raise ValueError("目标升级数量必须在 1 到 1000 之间")
        return target_count

    async def preview(self, project_id: UUID, options: DistillationOptions) -> DistillationPreview:
        seeds = await self._seeds(project_id, options)
        if not seeds:
            raise ValueError("没有符合条件的已通过样本；请调整来源或关键词筛选")
        target = min(options.target_count, len(seeds))
        return DistillationPreview(len(seeds), target, self._fingerprint(seeds[:target], options))

    async def prepare(self, project_id: UUID, options: DistillationOptions, fingerprint: str) -> UUID:
        seeds = (await self._seeds(project_id, options))[: options.target_count]
        if not seeds:
            raise ValueError("没有符合条件的已通过样本；请重新预览")
        if fingerprint != self._fingerprint(seeds, options):
            raise ValueError("蒸馏预览已失效：样本或配置已变化，请重新检查")
        run_id = uuid4()
        async with self.sessions() as session:
            project = await session.get(ProjectRow, project_id)
            if project is None or project.deleted_at is not None:
                raise LookupError("数据集不存在")
            session.add(PipelineRunRow(
                id=run_id,
                project_id=project_id,
                status=PipelineStatus.CREATED,
                current_stage=PipelineStatus.CREATED,
                total_items=len(seeds),
                configuration={
                    "run_type": "distillation",
                    "target_count": options.target_count,
                    "keyword": options.keyword,
                    "source_document_ids": [str(value) for value in options.source_document_ids],
                    "prompt_text": options.prompt_text,
                    "model_id": str(options.model_id) if options.model_id else None,
                    "llm": self._llm_signature(),
                },
                started_at=utc_now(),
            ))
            await session.flush()
            session.add_all(DistillationJobRow(run_id=run_id, source_sample_id=seed.id) for seed in seeds)
            await session.commit()
        return run_id

    async def execute(self, run_id: UUID) -> None:
        await self._set_running(run_id)
        while True:
            async with self.sessions() as session:
                run = await session.get(PipelineRunRow, run_id)
                job = await session.scalar(select(DistillationJobRow).where(
                    DistillationJobRow.run_id == run_id, DistillationJobRow.status == "pending"
                ).order_by(DistillationJobRow.created_at, DistillationJobRow.id).limit(1))
                if run is None or job is None:
                    break
                job.status = "running"
                seed = await session.get(TrainingSampleRow, job.source_sample_id)
                chunk = await session.get(ChunkRow, seed.chunk_id) if seed else None
                await session.commit()
            if seed is None or chunk is None:
                await self._finish_job(run_id, job.id, None, "原样本或来源内容块不存在")
                continue
            try:
                response = await self.client.generate(
                    self._messages(seed, chunk, run.configuration["prompt_text"]),
                    DistillationResponse,
                )
                candidate = self._candidate(seed, response, run_id, job.id)
                await self._finish_job(run_id, job.id, candidate, None)
            except Exception as exc:
                await self._finish_job(run_id, job.id, None, f"{type(exc).__name__}: {exc}"[:500])
                if isinstance(exc, QuotaExceededError):
                    break
        await self._complete(run_id)

    async def retry(self, run_id: UUID) -> None:
        async with self.sessions() as session:
            run = await session.get(PipelineRunRow, run_id)
            if run is None or run.configuration.get("run_type") != "distillation":
                raise LookupError("蒸馏任务不存在")
            jobs = (await session.scalars(select(DistillationJobRow).where(
                DistillationJobRow.run_id == run_id, DistillationJobRow.status == "failed"
            ))).all()
            for job in jobs:
                job.status, job.error_message, job.finished_at = "pending", None, None
            run.status, run.error_message, run.finished_at = PipelineStatus.CREATED, None, None
            await session.commit()
        await self.execute(run_id)

    async def _set_running(self, run_id: UUID) -> None:
        async with self.sessions() as session:
            run = await session.get(PipelineRunRow, run_id)
            if run is None or run.configuration.get("run_type") != "distillation":
                raise LookupError("蒸馏任务不存在")
            run.status = run.current_stage = PipelineStatus.DISTILLING
            await session.commit()

    async def _finish_job(
        self,
        run_id: UUID,
        job_id: UUID,
        candidate: TrainingSample | None,
        error: str | None,
    ) -> None:
        async with self.sessions() as session:
            run, job = await session.get(PipelineRunRow, run_id), await session.get(DistillationJobRow, job_id)
            if run is None or job is None:
                return
            if error:
                job.status, job.error_message, job.finished_at = "failed", error, utc_now()
                run.failed_items += 1
                await session.commit()
                return
            hashes = set((await session.scalars(select(TrainingSampleRow.content_hash).where(
                TrainingSampleRow.project_id == run.project_id,
                TrainingSampleRow.content_hash.is_not(None),
                TrainingSampleRow.validation_status == "passed",
                TrainingSampleRow.is_deleted.is_(False),
            ))).all())
            cleaned = self.cleaner.clean([candidate], {(run.project_id, value) for value in hashes})
            sample = (cleaned.accepted or cleaned.rejected)[0]
            issues = [*cleaned.issues, *self.validator.validate(sample)]
            if issues:
                job.status, job.error_message, job.finished_at = (
                    "filtered",
                    "; ".join(issue.rule for issue in issues)[:500],
                    utc_now(),
                )
                run.failed_items += 1
            else:
                session.add(TrainingSampleRow(
                    id=sample.id,
                    project_id=sample.project_id,
                    document_id=sample.document_id,
                    chunk_id=sample.chunk_id,
                    messages=[message.model_dump(mode="json") for message in sample.messages],
                    metadata_=sample.metadata,
                    content_hash=sample.content_hash,
                    review_status="pending",
                    validation_status="passed",
                    is_deleted=False,
                ))
                job.candidate_sample_id, job.status, job.finished_at = sample.id, "completed", utc_now()
                run.completed_items += 1
            await session.commit()

    async def _complete(self, run_id: UUID) -> None:
        async with self.sessions() as session:
            run = await session.get(PipelineRunRow, run_id)
            if run is not None:
                run.status = run.current_stage = PipelineStatus.READY_FOR_REVIEW
                run.finished_at = utc_now()
                await session.commit()

    async def _seeds(self, project_id: UUID, options: DistillationOptions) -> list[TrainingSampleRow]:
        async with self.sessions() as session:
            project = await session.get(ProjectRow, project_id)
            if project is None or project.deleted_at is not None:
                raise LookupError("数据集不存在")
            conditions = [TrainingSampleRow.project_id == project_id, TrainingSampleRow.review_status == "approved",
                          TrainingSampleRow.validation_status == "passed", TrainingSampleRow.is_deleted.is_(False),
                          TrainingSampleRow.superseded_at.is_(None)]
            if options.source_document_ids:
                conditions.append(TrainingSampleRow.document_id.in_(options.source_document_ids))
            if options.keyword:
                conditions.append(TrainingSampleRow.messages.cast(Text).ilike(f"%{options.keyword.strip()}%"))
            return (await session.scalars(select(TrainingSampleRow).where(*conditions).order_by(
                TrainingSampleRow.created_at, TrainingSampleRow.id
            ))).all()

    @staticmethod
    def _candidate(
        seed: TrainingSampleRow,
        response: DistillationResponse,
        run_id: UUID,
        job_id: UUID,
    ) -> TrainingSample:
        assistant_count = sum(message["role"] == "assistant" for message in seed.messages)
        if len(response.assistant_messages) != assistant_count:
            raise ValueError("教师回复数量必须与原样本 assistant 消息数量一致")
        replies = iter(response.assistant_messages)
        messages = [
            Message(
                role=item["role"],
                content=next(replies) if item["role"] == "assistant" else item["content"],
            )
            for item in seed.messages
        ]
        return TrainingSample(
            project_id=seed.project_id, document_id=seed.document_id, chunk_id=seed.chunk_id, messages=messages,
            metadata={**seed.metadata_, "generator": "distillation", "distillation_source_id": str(seed.id),
                      "distillation_run_id": str(run_id), "distillation_job_id": str(job_id)},
        )

    @staticmethod
    def _messages(seed: TrainingSampleRow, chunk: ChunkRow, prompt: str) -> list[Message]:
        return [
            Message(
                role=MessageRole.SYSTEM,
                content="你是训练数据教师。只升级 assistant 回复，严格依据来源内容，不得改变 system/user 消息。\n"
                + prompt,
            ),
            Message(
                role=MessageRole.USER,
                content=(
                    f"来源内容：\n{chunk.content}\n\n原始训练样本：\n"
                    f"{json.dumps(seed.messages, ensure_ascii=False)}"
                ),
            ),
        ]

    @staticmethod
    def _fingerprint(seeds: list[TrainingSampleRow], options: DistillationOptions) -> str:
        payload = {"seeds": [(str(seed.id), seed.updated_at.isoformat() if seed.updated_at else "") for seed in seeds],
                   "target": options.target_count, "keyword": options.keyword,
                   "sources": [str(value) for value in options.source_document_ids], "prompt": options.prompt_text,
                   "model": str(options.model_id)}
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()

    def _llm_signature(self) -> dict[str, object]:
        settings = getattr(self.client, "settings", None)
        return {} if settings is None else {"base_url": settings.base_url, "model": settings.model,
                                            "temperature": settings.temperature, "max_tokens": settings.max_tokens}
