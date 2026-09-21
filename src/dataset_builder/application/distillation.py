"""Regenerate approved answers independently with a teacher model."""

import hashlib
import json
import logging
from dataclasses import dataclass
from time import perf_counter
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
from dataset_builder.generators.prompts import DISTILLATION_FORMAT
from dataset_builder.llm import LLMClient, QuotaExceededError
from dataset_builder.models import Message, MessageRole, PipelineStatus, TrainingSample, utc_now
from dataset_builder.validators import SampleValidator

logger = logging.getLogger(__name__)


class DistillationResponse(BaseModel):
    answer: str = Field(min_length=1)

    @field_validator("answer")
    @classmethod
    def nonblank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("answer 不能为空")
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
    estimated_requests: int
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
        selected = seeds[:target]
        estimated_requests = sum(
            message["role"] == MessageRole.ASSISTANT for seed in selected for message in seed.messages
        )
        return DistillationPreview(
            eligible_count=len(seeds),
            target_count=target,
            estimated_requests=estimated_requests,
            fingerprint=self._fingerprint(selected, options),
        )

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
                    "estimated_requests": sum(
                        message["role"] == MessageRole.ASSISTANT for seed in seeds for message in seed.messages
                    ),
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
        logger.info(
            "已创建教师蒸馏任务：运行编号 %s，项目编号 %s，原样本 %d 条，预计模型请求 %d 次",
            run_id,
            project_id,
            len(seeds),
            sum(message["role"] == MessageRole.ASSISTANT for seed in seeds for message in seed.messages),
        )
        return run_id

    async def execute(self, run_id: UUID) -> None:
        started_at = perf_counter()
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
            logger.info(
                "开始处理蒸馏样本：运行编号 %s，任务编号 %s，原样本编号 %s",
                run_id,
                job.id,
                job.source_sample_id,
            )
            if seed is None or chunk is None:
                await self._finish_job(run_id, job.id, None, "原样本或来源内容块不存在")
                continue
            try:
                candidate = await self._candidate(
                    seed,
                    chunk,
                    run.configuration["prompt_text"],
                    run_id,
                    job.id,
                )
            except Exception as exc:
                error = f"ModelError: {type(exc).__name__}: {exc}"[:500]
                await self._finish_job(run_id, job.id, None, error)
                if isinstance(exc, QuotaExceededError):
                    break
                continue
            try:
                await self._finish_job(run_id, job.id, candidate, None)
            except Exception as exc:
                logger.exception("保存教师蒸馏候选失败：运行编号 %s，任务编号 %s", run_id, job.id)
                error = f"PersistenceError: {type(exc).__name__}: {exc}"[:500]
                await self._finish_job(run_id, job.id, None, error)
        completed, failed = await self._complete(run_id)
        logger.info(
            "教师蒸馏任务结束：运行编号 %s，生成候选 %d 条，失败或过滤 %d 条，耗时 %.2f 秒",
            run_id,
            completed,
            failed,
            perf_counter() - started_at,
        )

    async def retry(self, run_id: UUID) -> None:
        async with self.sessions() as session:
            run = await session.get(PipelineRunRow, run_id)
            if run is None or run.configuration.get("run_type") != "distillation":
                raise LookupError("蒸馏任务不存在")
            jobs = (await session.scalars(select(DistillationJobRow).where(
                DistillationJobRow.run_id == run_id
            ))).all()
            for job in jobs:
                if job.status == "failed":
                    job.status, job.error_message, job.finished_at = "pending", None, None
            run.completed_items = sum(job.status == "completed" for job in jobs)
            run.failed_items = sum(job.status == "filtered" for job in jobs)
            run.status, run.error_message, run.finished_at = PipelineStatus.CREATED, None, None
            await session.commit()
        logger.info(
            "开始重试教师蒸馏任务：运行编号 %s，待重试 %d 条，保留规则过滤 %d 条",
            run_id,
            sum(job.status == "pending" for job in jobs),
            run.failed_items,
        )
        await self.execute(run_id)

    async def _set_running(self, run_id: UUID) -> None:
        async with self.sessions() as session:
            run = await session.get(PipelineRunRow, run_id)
            if run is None or run.configuration.get("run_type") != "distillation":
                raise LookupError("蒸馏任务不存在")
            run.status = run.current_stage = PipelineStatus.DISTILLING
            await session.commit()
            logger.info(
                "教师蒸馏任务开始：运行编号 %s，原样本总数 %d，预计模型请求 %s 次",
                run_id,
                run.total_items,
                run.configuration.get("estimated_requests", "未知"),
            )

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
                logger.warning(
                    "教师蒸馏处理失败：运行编号 %s，任务编号 %s，原样本编号 %s，原因 %s",
                    run_id,
                    job_id,
                    job.source_sample_id,
                    error,
                )
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
                issue_summary = "; ".join(issue.rule for issue in issues)[:500]
                job.status, job.error_message, job.finished_at = (
                    "filtered",
                    issue_summary,
                    utc_now(),
                )
                run.failed_items += 1
                logger.warning(
                    "教师蒸馏候选被过滤：运行编号 %s，任务编号 %s，原样本编号 %s，规则 %s",
                    run_id,
                    job_id,
                    job.source_sample_id,
                    issue_summary,
                )
            else:
                candidate_row = TrainingSampleRow(
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
                )
                await self._attach_candidate(session, job, candidate_row)
                job.candidate_sample_id, job.status, job.finished_at = sample.id, "completed", utc_now()
                run.completed_items += 1
                logger.info(
                    "教师蒸馏候选已生成：运行编号 %s，任务编号 %s，原样本编号 %s，候选编号 %s，进度 %d/%d",
                    run_id,
                    job_id,
                    job.source_sample_id,
                    sample.id,
                    run.completed_items + run.failed_items,
                    run.total_items,
                )
            await session.commit()

    @staticmethod
    async def _attach_candidate(
        session: AsyncSession,
        job: DistillationJobRow,
        candidate: TrainingSampleRow,
    ) -> None:
        session.add(candidate)
        # candidate_sample_id has a real foreign key but no ORM relationship. Flush the
        # candidate first so SQLite and PostgreSQL never observe the reference before its row.
        await session.flush([candidate])
        job.candidate_sample_id = candidate.id

    async def _complete(self, run_id: UUID) -> tuple[int, int]:
        async with self.sessions() as session:
            run = await session.get(PipelineRunRow, run_id)
            if run is not None:
                run.status = run.current_stage = PipelineStatus.READY_FOR_REVIEW
                run.finished_at = utc_now()
                await session.commit()
                return run.completed_items, run.failed_items
        return 0, 0

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

    async def _candidate(
        self,
        seed: TrainingSampleRow,
        chunk: ChunkRow,
        prompt: str,
        run_id: UUID,
        job_id: UUID,
    ) -> TrainingSample:
        messages: list[Message] = []
        assistant_turn = 0
        for item in seed.messages:
            if item["role"] != MessageRole.ASSISTANT:
                messages.append(Message.model_validate(item))
                continue
            if not messages or messages[-1].role != MessageRole.USER:
                raise ValueError("原样本消息顺序无效，无法独立生成教师回答")
            assistant_turn += 1
            logger.info(
                "请求教师回答：运行编号 %s，任务编号 %s，原样本编号 %s，第 %d 轮",
                run_id,
                job_id,
                seed.id,
                assistant_turn,
            )
            response = await self.client.generate(
                self._messages(messages, chunk, prompt),
                DistillationResponse,
            )
            messages.append(Message(role=MessageRole.ASSISTANT, content=response.answer))
        return TrainingSample(
            project_id=seed.project_id, document_id=seed.document_id, chunk_id=seed.chunk_id, messages=messages,
            metadata={**seed.metadata_, "generator": "distillation", "distillation_source_id": str(seed.id),
                      "distillation_run_id": str(run_id), "distillation_job_id": str(job_id),
                      "distillation_method": "independent_answer"},
        )

    @staticmethod
    def _messages(history: list[Message], chunk: ChunkRow, prompt: str) -> list[Message]:
        instruction = prompt.split("\n只返回一个 json 对象", 1)[0].strip()
        effective_prompt = f"{instruction}\n{DISTILLATION_FORMAT}"
        original_system = "\n".join(
            message.content for message in history if message.role == MessageRole.SYSTEM
        )
        conversation = [message for message in history if message.role != MessageRole.SYSTEM]
        return [
            Message(
                role=MessageRole.SYSTEM,
                content=(
                    "你是训练数据教师。请严格依据来源内容，独立回答对话中最后一条 user 消息。"
                    "你看不到也不得猜测原样本的旧回答。不要改写问题，不要添加来源无法支持的事实。\n"
                    f"{effective_prompt}\n\n来源内容：\n{chunk.content}"
                    + (f"\n\n原始 system 约束：\n{original_system}" if original_system else "")
                ),
            ),
            *conversation,
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
