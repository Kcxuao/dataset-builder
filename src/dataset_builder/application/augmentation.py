"""Generate traceable, multi-angle training samples from approved project samples."""

import hashlib
import json
from dataclasses import dataclass
from uuid import UUID, uuid4

from pydantic import BaseModel, Field
from sqlalchemy import Text, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dataset_builder.cleaners import BasicCleaner
from dataset_builder.db.orm import (
    AugmentationJobRow,
    ChunkRow,
    PipelineRunRow,
    ProjectRow,
    TrainingSampleRow,
)
from dataset_builder.llm import LLMClient, QuotaExceededError
from dataset_builder.models import Message, MessageRole, PipelineStatus, TrainingSample, utc_now
from dataset_builder.validators import SampleValidator

STRATEGIES = {
    "rewrite": ("表达改写", "保持事实不变，使用不同的提问方式和回答表达。"),
    "angle": ("认知角度", "从定义、原因、过程、比较或影响等不同知识角度组织问题。"),
    "deepen": ("难度深化", "增加合理的约束或推理步骤，但只能使用来源中已经给出的事实。"),
    "audience": ("角色视角", "面向不同受众调整问题和回答的解释方式。"),
    "scenario": ("场景应用", "把知识放进具体使用场景，形成可解决的任务。"),
}


class AugmentationItem(BaseModel):
    messages: list[Message] = Field(min_length=2)


class AugmentationResponse(BaseModel):
    items: list[AugmentationItem] = Field(min_length=1, max_length=1)


@dataclass(frozen=True)
class AugmentationOptions:
    strategies: tuple[str, ...]
    target_count: int
    keyword: str | None
    source_document_ids: tuple[UUID, ...]
    prompt_text: str
    model_id: UUID | None


@dataclass(frozen=True)
class AugmentationPreview:
    eligible_count: int
    target_count: int
    max_attempts: int
    distribution: list[dict[str, object]]
    fingerprint: str


class AugmentationService:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], client: LLMClient) -> None:
        self.sessions = sessions
        self.client = client
        self.cleaner = BasicCleaner()
        self.validator = SampleValidator()

    @staticmethod
    def validate_options(strategies: list[str], target_count: int) -> tuple[str, ...]:
        selected = tuple(dict.fromkeys(strategies))
        if not selected or any(item not in STRATEGIES for item in selected):
            raise ValueError("请至少选择一种有效的扩增策略")
        if not 1 <= target_count <= 1000:
            raise ValueError("目标新增数量必须在 1 到 1000 之间")
        return selected

    async def preview(self, project_id: UUID, options: AugmentationOptions) -> AugmentationPreview:
        seeds = await self._seeds(project_id, options)
        if not seeds:
            raise ValueError("没有符合条件的已通过样本；请调整来源或关键词筛选")
        distribution = self._distribution(seeds, options.strategies, options.target_count)
        return AugmentationPreview(
            eligible_count=len(seeds),
            target_count=options.target_count,
            max_attempts=options.target_count * 2,
            distribution=distribution,
            fingerprint=self._fingerprint(seeds, options),
        )

    async def prepare(self, project_id: UUID, options: AugmentationOptions, fingerprint: str) -> UUID:
        seeds = await self._seeds(project_id, options)
        if not seeds:
            raise ValueError("没有符合条件的已通过样本；请重新预览")
        if fingerprint != self._fingerprint(seeds, options):
            raise ValueError("扩增预览已失效：种子样本或配置已变化，请重新检查")
        run_id = uuid4()
        pairs = [(seed, strategy) for seed in seeds for strategy in options.strategies]
        async with self.sessions() as session:
            project = await session.get(ProjectRow, project_id)
            if project is None or project.deleted_at is not None:
                raise LookupError("数据集不存在")
            run = PipelineRunRow(
                id=run_id,
                project_id=project_id,
                status=PipelineStatus.CREATED,
                current_stage=PipelineStatus.CREATED,
                total_items=options.target_count,
                configuration={
                    "run_type": "augmentation",
                    "strategies": list(options.strategies),
                    "target_count": options.target_count,
                    "max_attempts": options.target_count * 2,
                    "keyword": options.keyword,
                    "source_document_ids": [str(value) for value in options.source_document_ids],
                    "prompt_text": options.prompt_text,
                    "model_id": str(options.model_id) if options.model_id else None,
                    "llm": self._llm_signature(),
                },
                started_at=utc_now(),
            )
            session.add(run)
            # Jobs only carry a scalar FK rather than an ORM relationship. Flush the parent
            # explicitly so PostgreSQL always observes the PipelineRun before its child jobs.
            await session.flush([run])
            for index in range(options.target_count * 2):
                seed, strategy = pairs[index % len(pairs)]
                session.add(
                    AugmentationJobRow(
                        run_id=run_id,
                        seed_sample_id=seed.id,
                        strategy=strategy,
                        round=index // len(pairs) + 1,
                    )
                )
            await session.commit()
        return run_id

    async def execute(self, run_id: UUID) -> None:
        async with self.sessions() as session:
            run = await session.get(PipelineRunRow, run_id)
            if run is None or run.configuration.get("run_type") != "augmentation":
                raise LookupError("扩增任务不存在")
            run.status = PipelineStatus.AUGMENTING
            run.current_stage = PipelineStatus.AUGMENTING
            await session.commit()

        while True:
            async with self.sessions() as session:
                run = await session.get(PipelineRunRow, run_id)
                if run is None:
                    return
                if run.completed_items >= run.total_items:
                    break
                job = await session.scalar(
                    select(AugmentationJobRow)
                    .where(AugmentationJobRow.run_id == run_id, AugmentationJobRow.status == "pending")
                    .order_by(AugmentationJobRow.created_at, AugmentationJobRow.id)
                    .limit(1)
                )
                if job is None:
                    break
                job.status = "running"
                seed = await session.get(TrainingSampleRow, job.seed_sample_id)
                chunk = await session.get(ChunkRow, seed.chunk_id) if seed else None
                await session.commit()
            if seed is None or chunk is None:
                await self._finish_job(run_id, job.id, None, "父样本或来源内容块不存在")
                continue
            try:
                messages = self._messages(seed, chunk, job.strategy, job.round, run.configuration["prompt_text"])
                response = await self.client.generate(messages, AugmentationResponse)
                await self._finish_job(run_id, job.id, response.items[0], None)
            except Exception as exc:
                await self._finish_job(run_id, job.id, None, f"{type(exc).__name__}: {exc}"[:500])
                if isinstance(exc, QuotaExceededError):
                    break

        async with self.sessions() as session:
            run = await session.get(PipelineRunRow, run_id)
            if run is not None:
                run.status = PipelineStatus.READY_FOR_REVIEW
                run.current_stage = PipelineStatus.READY_FOR_REVIEW
                run.finished_at = utc_now()
                await session.commit()

    async def retry(self, run_id: UUID) -> None:
        async with self.sessions() as session:
            run = await session.get(PipelineRunRow, run_id)
            if run is None or run.configuration.get("run_type") != "augmentation":
                raise LookupError("扩增任务不存在")
            jobs = (
                await session.scalars(
                    select(AugmentationJobRow).where(
                        AugmentationJobRow.run_id == run_id, AugmentationJobRow.status == "failed"
                    )
                )
            ).all()
            for job in jobs:
                job.status = "pending"
                job.error_message = None
            run.status = PipelineStatus.CREATED
            run.error_message = None
            run.finished_at = None
            await session.commit()
        await self.execute(run_id)

    async def _finish_job(self, run_id: UUID, job_id: UUID, item: AugmentationItem | None, error: str | None) -> None:
        async with self.sessions() as session:
            run = await session.get(PipelineRunRow, run_id)
            job = await session.get(AugmentationJobRow, job_id)
            if run is None or job is None:
                return
            if error:
                job.status = "failed"
                job.error_message = error
                job.finished_at = utc_now()
                run.failed_items += 1
                await session.commit()
                return
            seed = await session.get(TrainingSampleRow, job.seed_sample_id)
            if seed is None:
                job.status = "failed"
                job.error_message = "父样本不存在"
                run.failed_items += 1
                await session.commit()
                return
            hashes = set(
                (await session.scalars(select(TrainingSampleRow.content_hash).where(
                    TrainingSampleRow.project_id == run.project_id,
                    TrainingSampleRow.content_hash.is_not(None),
                    TrainingSampleRow.validation_status == "passed",
                    TrainingSampleRow.is_deleted.is_(False),
                ))).all()
            )
            candidate = TrainingSample(
                project_id=run.project_id,
                document_id=seed.document_id,
                chunk_id=seed.chunk_id,
                messages=item.messages,
                metadata={
                    **seed.metadata_,
                    "generator": "augmentation",
                    "augmentation_strategy": job.strategy,
                    "augmentation_round": job.round,
                    "parent_sample_id": str(seed.id),
                },
                parent_sample_id=seed.id,
                generation_run_id=run_id,
            )
            cleaned = self.cleaner.clean([candidate], {(run.project_id, value) for value in hashes})
            sample = (cleaned.accepted or cleaned.rejected)[0]
            issues = [*cleaned.issues, *self.validator.validate(sample)]
            if issues:
                job.status = "filtered"
                job.error_message = "; ".join(issue.rule for issue in issues)[:500]
                job.finished_at = utc_now()
                run.failed_items += 1
            else:
                session.add(
                    TrainingSampleRow(
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
                        parent_sample_id=seed.id,
                        generation_run_id=run_id,
                    )
                )
                job.status = "completed"
                job.generated_count = 1
                job.finished_at = utc_now()
                run.completed_items += 1
            await session.commit()

    async def _seeds(self, project_id: UUID, options: AugmentationOptions) -> list[TrainingSampleRow]:
        async with self.sessions() as session:
            project = await session.get(ProjectRow, project_id)
            if project is None or project.deleted_at is not None:
                raise LookupError("数据集不存在")
            conditions = [
                TrainingSampleRow.project_id == project_id,
                TrainingSampleRow.review_status == "approved",
                TrainingSampleRow.validation_status == "passed",
                TrainingSampleRow.is_deleted.is_(False),
                TrainingSampleRow.superseded_at.is_(None),
            ]
            if options.source_document_ids:
                conditions.append(TrainingSampleRow.document_id.in_(options.source_document_ids))
            if options.keyword:
                conditions.append(TrainingSampleRow.messages.cast(Text).ilike(f"%{options.keyword.strip()}%"))
            query = select(TrainingSampleRow).where(*conditions).order_by(
                TrainingSampleRow.created_at, TrainingSampleRow.id
            )
            return (await session.scalars(query)).all()

    @staticmethod
    def _distribution(
        seeds: list[TrainingSampleRow], strategies: tuple[str, ...], target: int
    ) -> list[dict[str, object]]:
        counts = {strategy: 0 for strategy in strategies}
        for index in range(target):
            counts[strategies[index % len(strategies)]] += 1
        return [{"id": strategy, "name": STRATEGIES[strategy][0], "count": counts[strategy]} for strategy in strategies]

    @staticmethod
    def _fingerprint(seeds: list[TrainingSampleRow], options: AugmentationOptions) -> str:
        payload = {
            "seeds": [(str(seed.id), seed.updated_at.isoformat() if seed.updated_at else "") for seed in seeds],
            "strategies": options.strategies, "target": options.target_count, "keyword": options.keyword,
            "sources": [str(value) for value in options.source_document_ids],
            "prompt": options.prompt_text,
            "model": str(options.model_id),
        }
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()

    @staticmethod
    def _messages(
        seed: TrainingSampleRow, chunk: ChunkRow, strategy: str, round_number: int, prompt: str
    ) -> list[Message]:
        source_messages = json.dumps(seed.messages, ensure_ascii=False)
        return [
            Message(role=MessageRole.SYSTEM, content=(
                "你负责扩增高质量训练数据。不得添加来源和种子样本没有支持的事实；"
                "不要照抄种子样本，输出必须是新的、可独立使用的训练对。\n" + prompt
            )),
            Message(role=MessageRole.USER, content=(
                f"扩增策略：{STRATEGIES[strategy][0]}。{STRATEGIES[strategy][1]}\n"
                f"第 {round_number} 轮变体。\n原始来源内容：\n{chunk.content}\n\n"
                f"已通过的种子样本：\n{source_messages}"
            )),
        ]

    def _llm_signature(self) -> dict[str, object]:
        settings = getattr(self.client, "settings", None)
        if settings is None:
            return {}
        return {
            "base_url": settings.base_url,
            "model": settings.model,
            "temperature": settings.temperature,
            "max_tokens": settings.max_tokens,
        }
