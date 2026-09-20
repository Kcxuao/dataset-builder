"""Persist import, split, generation, cleaning, and validation progress."""

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dataset_builder.cleaners import BasicCleaner
from dataset_builder.db.orm import (
    ChunkRow,
    PipelineRunRow,
    ProjectRow,
    SourceDocumentRow,
    TrainingSampleRow,
    ValidationIssueRow,
)
from dataset_builder.generators import InstructionGenerator, QAGenerator
from dataset_builder.llm import LLMClient
from dataset_builder.models import Chunk, PipelineStatus, TrainingSample, ValidationIssue, utc_now
from dataset_builder.parsers import CSVParser, ImportSource, JSONLParser, JSONParser, MarkdownParser, TextParser
from dataset_builder.splitters import FixedLengthSplitter, MarkdownHeadingSplitter, ParagraphSplitter
from dataset_builder.validators import SampleValidator


@dataclass(frozen=True)
class BuildSummary:
    project_id: UUID
    run_id: UUID
    document_count: int
    chunk_count: int
    sample_count: int
    failed_chunk_count: int


class BuildService:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], client: LLMClient) -> None:
        self.sessions = sessions
        self.client = client
        self.cleaner = BasicCleaner()
        self.validator = SampleValidator()

    async def build(
        self,
        path: Path,
        project_name: str,
        generator_mode: str = "qa",
        splitter_mode: str = "auto",
        max_chunk_length: int = 1000,
        overlap: int = 0,
        content_field: str | None = None,
        content_columns: tuple[str, ...] = (),
    ) -> BuildSummary:
        if generator_mode not in {"qa", "instruction"}:
            raise ValueError("generator_mode must be qa or instruction")
        if splitter_mode not in {"auto", "fixed", "paragraph", "markdown"}:
            raise ValueError("splitter_mode must be auto, fixed, paragraph, or markdown")
        if not project_name.strip():
            raise ValueError("project_name must not be blank")
        extension = path.suffix.lower()
        if extension not in {".txt", ".md", ".markdown", ".json", ".jsonl", ".csv"}:
            raise ValueError(f"Unsupported input format: {extension}")
        if extension in {".json", ".jsonl"} and not content_field:
            raise ValueError("JSON and JSONL imports require --content-field")
        if extension == ".csv" and not content_columns:
            raise ValueError("CSV imports require --content-column")
        if content_field and extension not in {".json", ".jsonl"}:
            raise ValueError("--content-field is only supported for JSON and JSONL")
        if content_columns and extension != ".csv":
            raise ValueError("--content-column is only supported for CSV")

        project_id, run_id = uuid4(), uuid4()
        async with self.sessions() as session:
            session.add(ProjectRow(id=project_id, name=project_name.strip()))
            await session.flush()
            session.add(PipelineRunRow(
                id=run_id, project_id=project_id, status=PipelineStatus.CREATED,
                configuration={
                    "generator": generator_mode, "splitter": splitter_mode,
                    "max_chunk_length": max_chunk_length, "overlap": overlap,
                    "content_field": content_field, "content_columns": list(content_columns),
                    "llm": self._llm_signature(),
                },
                started_at=utc_now(),
            ))
            await session.commit()

        try:
            return await self._process(
                project_id, run_id, path, generator_mode, splitter_mode,
                max_chunk_length, overlap, content_field, content_columns,
            )
        except Exception as exc:
            async with self.sessions() as session:
                run = await session.get(PipelineRunRow, run_id)
                run.status = PipelineStatus.FAILED
                run.error_message = f"{type(exc).__name__}: {exc}"[:500]
                run.finished_at = utc_now()
                await session.commit()
            raise

    async def _process(
        self,
        project_id: UUID,
        run_id: UUID,
        path: Path,
        generator_mode: str,
        splitter_mode: str,
        max_chunk_length: int,
        overlap: int,
        content_field: str | None,
        content_columns: tuple[str, ...],
    ) -> BuildSummary:
        parser = {
            ".txt": TextParser,
            ".md": MarkdownParser,
            ".markdown": MarkdownParser,
            ".json": JSONParser,
            ".jsonl": JSONLParser,
            ".csv": CSVParser,
        }[path.suffix.lower()]()
        async with self.sessions() as session:
            run = await session.get(PipelineRunRow, run_id)
            run.status = PipelineStatus.PARSING
            run.current_stage = PipelineStatus.PARSING
            await session.commit()
        documents = parser.parse(ImportSource(
            path=path, project_id=project_id,
            content_field=content_field, content_columns=content_columns,
        ))

        mode = "markdown" if splitter_mode == "auto" and path.suffix.lower() in {".md", ".markdown"} else splitter_mode
        if mode == "auto":
            mode = "paragraph"
        splitter = {
            "fixed": FixedLengthSplitter,
            "paragraph": ParagraphSplitter,
            "markdown": MarkdownHeadingSplitter,
        }[mode](max_length=max_chunk_length, overlap=overlap)
        chunks: list[Chunk] = []
        for document in documents:
            chunks.extend(splitter.split(document))
        async with self.sessions() as session:
            run = await session.get(PipelineRunRow, run_id)
            run.status = PipelineStatus.SPLITTING
            run.current_stage = PipelineStatus.SPLITTING
            run.total_items = len(chunks)
            for document in documents:
                session.add(SourceDocumentRow(
                    id=document.id, project_id=project_id, source_name=document.source_name,
                    source_type=document.source_type, content=document.content,
                    metadata_=document.metadata, parse_status=document.parse_status,
                ))
            await session.flush()
            for chunk in chunks:
                session.add(ChunkRow(
                    id=chunk.id, document_id=chunk.document_id, index=chunk.index,
                    content=chunk.content, content_hash=chunk.content_hash,
                    metadata_=chunk.metadata, generation_status="pending",
                ))
            await session.commit()

        sample_count, failed_count = await self._generate_chunks(project_id, run_id, chunks, generator_mode, set())
        return BuildSummary(project_id, run_id, len(documents), len(chunks), sample_count, failed_count)

    async def retry_failed(self, project_id: UUID) -> BuildSummary:
        async with self.sessions() as session:
            run = await session.scalar(
                select(PipelineRunRow).where(PipelineRunRow.project_id == project_id)
                .order_by(PipelineRunRow.started_at.desc()).limit(1)
            )
            if run is None:
                raise LookupError(f"Project {project_id} has no pipeline run")
            if run.configuration.get("llm") != self._llm_signature():
                raise ValueError("LLM configuration differs from the original run")
            mode = run.configuration["generator"]
            rows = (await session.scalars(
                select(ChunkRow).join(SourceDocumentRow)
                .where(
                    SourceDocumentRow.project_id == project_id,
                    ChunkRow.generation_status.in_(["failed", "pending"]),
                )
                .order_by(SourceDocumentRow.created_at, ChunkRow.index)
            )).all()
            chunks = [Chunk(
                id=row.id, document_id=row.document_id, index=row.index,
                content=row.content, metadata=row.metadata_,
            ) for row in rows]
            hashes = (await session.scalars(
                select(TrainingSampleRow.content_hash).where(
                    TrainingSampleRow.project_id == project_id,
                    TrainingSampleRow.validation_status == "passed",
                    TrainingSampleRow.content_hash.is_not(None),
                )
            )).all()
            document_count = await session.scalar(
                select(func.count(SourceDocumentRow.id)).where(SourceDocumentRow.project_id == project_id)
            )
            run.failed_items = 0
            run.status = PipelineStatus.GENERATING
            run.current_stage = PipelineStatus.GENERATING
            run.finished_at = None
            await session.commit()
            run_id = run.id
        sample_count, failed_count = await self._generate_chunks(
            project_id, run_id, chunks, mode, {(project_id, value) for value in hashes}
        )
        return BuildSummary(project_id, run_id, document_count, len(chunks), sample_count, failed_count)

    async def _generate_chunks(
        self,
        project_id: UUID,
        run_id: UUID,
        chunks: list[Chunk],
        generator_mode: str,
        seen: set[tuple[UUID, str]],
    ) -> tuple[int, int]:
        generator = (QAGenerator if generator_mode == "qa" else InstructionGenerator)(self.client, project_id)
        sample_count = 0
        failed_count = 0
        for chunk in chunks:
            try:
                generated = await generator.generate(chunk)
            except Exception as exc:
                failed_count += 1
                async with self.sessions() as session:
                    row = await session.get(ChunkRow, chunk.id)
                    run = await session.get(PipelineRunRow, run_id)
                    row.generation_status = "failed"
                    row.metadata_ = {**row.metadata_, "generation_error": f"{type(exc).__name__}: {exc}"[:500]}
                    run.failed_items += 1
                    await session.commit()
                continue

            cleaned = self.cleaner.clean(generated, seen)
            issues_by_id: dict[UUID, list[ValidationIssue]] = {}
            for issue in cleaned.issues:
                issues_by_id.setdefault(issue.sample_id, []).append(issue)
            new_hashes: set[tuple[UUID, str]] = set()
            async with self.sessions() as session:
                row = await session.get(ChunkRow, chunk.id)
                run = await session.get(PipelineRunRow, run_id)
                for sample in [*cleaned.accepted, *cleaned.rejected]:
                    issues = issues_by_id.get(sample.id, []) + self.validator.validate(sample)
                    await self._add_sample(session, sample, issues)
                    if not issues:
                        new_hashes.add((sample.project_id, sample.content_hash))
                row.generation_status = "success"
                row.metadata_ = {key: value for key, value in row.metadata_.items() if key != "generation_error"}
                run.status = PipelineStatus.GENERATING
                run.current_stage = PipelineStatus.GENERATING
                run.completed_items += 1
                await session.commit()
            seen.update(new_hashes)
            sample_count += len(cleaned.accepted) + len(cleaned.rejected)

        async with self.sessions() as session:
            run = await session.get(PipelineRunRow, run_id)
            run.status = PipelineStatus.READY_FOR_REVIEW
            run.current_stage = PipelineStatus.READY_FOR_REVIEW
            run.finished_at = utc_now()
            await session.commit()
        return sample_count, failed_count

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

    @staticmethod
    async def _add_sample(session: AsyncSession, sample: TrainingSample, issues: list[ValidationIssue]) -> None:
        session.add(TrainingSampleRow(
            id=sample.id, project_id=sample.project_id, document_id=sample.document_id,
            chunk_id=sample.chunk_id, messages=[message.model_dump(mode="json") for message in sample.messages],
            metadata_=sample.metadata, content_hash=sample.content_hash,
            review_status="pending", validation_status="failed" if issues else "passed", is_deleted=False,
        ))
        await session.flush()
        for issue in issues:
            session.add(ValidationIssueRow(
                id=issue.id, sample_id=sample.id, rule=issue.rule,
                severity=issue.severity, message=issue.message,
            ))
