"""Read-only, zero-model quality statistics for a project."""

from collections import Counter
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from dataset_builder.db.orm import ChunkRow, ProjectRow, SourceDocumentRow, TrainingSampleRow, ValidationIssueRow


class QualitySummaryService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def summary(self, project_id: UUID) -> dict[str, object]:
        project = await self.session.get(ProjectRow, project_id)
        if project is None or project.deleted_at is not None:
            raise LookupError("数据集不存在")
        sample_conditions = (
            TrainingSampleRow.project_id == project_id,
            TrainingSampleRow.is_deleted.is_(False),
            TrainingSampleRow.superseded_at.is_(None),
        )
        chunk_rows = (
            await self.session.execute(
                select(ChunkRow.generation_status, func.count())
                .join(SourceDocumentRow)
                .where(SourceDocumentRow.project_id == project_id)
                .group_by(ChunkRow.generation_status)
            )
        ).all()
        sample_rows = (
            await self.session.execute(
                select(TrainingSampleRow.review_status, TrainingSampleRow.validation_status, func.count())
                .where(*sample_conditions)
                .group_by(TrainingSampleRow.review_status, TrainingSampleRow.validation_status)
            )
        ).all()
        issue_rows = (
            await self.session.execute(
                select(ValidationIssueRow.rule, func.count())
                .join(TrainingSampleRow)
                .where(*sample_conditions)
                .group_by(ValidationIssueRow.rule)
                .order_by(func.count().desc())
                .limit(5)
            )
        ).all()
        source_rows = (
            await self.session.execute(
                select(SourceDocumentRow.source_name, func.count(TrainingSampleRow.id))
                .join(TrainingSampleRow, TrainingSampleRow.document_id == SourceDocumentRow.id)
                .where(*sample_conditions)
                .group_by(SourceDocumentRow.source_name)
                .order_by(func.count(TrainingSampleRow.id).desc())
            )
        ).all()
        messages = (await self.session.scalars(select(TrainingSampleRow.messages).where(*sample_conditions))).all()
        lengths = [len(str(message.get("content", ""))) for batch in messages for message in batch]
        buckets = {"0-100": 0, "101-500": 0, "501-1000": 0, "1001+": 0}
        for length in lengths:
            buckets[
                "0-100" if length <= 100 else "101-500" if length <= 500 else "501-1000" if length <= 1000 else "1001+"
            ] += 1
        duplicate_rows = (
            await self.session.execute(
                select(TrainingSampleRow.content_hash, func.count())
                .where(*sample_conditions, TrainingSampleRow.content_hash.is_not(None))
                .group_by(TrainingSampleRow.content_hash)
                .having(func.count() > 1)
            )
        ).all()
        exportable_count = await self.session.scalar(
            select(func.count())
            .select_from(TrainingSampleRow)
            .where(
                *sample_conditions,
                TrainingSampleRow.review_status == "approved",
                TrainingSampleRow.validation_status == "passed",
            )
        )
        original_count = await self.session.scalar(
            select(func.count())
            .select_from(TrainingSampleRow)
            .where(*sample_conditions, TrainingSampleRow.parent_sample_id.is_(None))
        )
        augmented_count = await self.session.scalar(
            select(func.count())
            .select_from(TrainingSampleRow)
            .where(*sample_conditions, TrainingSampleRow.parent_sample_id.is_not(None))
        )
        metadata_rows = (
            await self.session.scalars(select(TrainingSampleRow.metadata_).where(*sample_conditions))
        ).all()
        distilled_count = sum(metadata.get("generator") == "distillation" for metadata in metadata_rows)
        chunks = Counter({status: count for status, count in chunk_rows})
        reviews = Counter()
        validations = Counter()
        for review, validation, count in sample_rows:
            reviews[review] += count
            validations[validation] += count
        return {
            "scope": "已排除已删除和已替代样本；读取统计不调用模型。",
            "chunks": {"success": chunks["success"], "failed": chunks["failed"], "pending": chunks["pending"]},
            "reviews": dict(reviews),
            "validations": dict(validations),
            "issues": [{"rule": rule, "count": count} for rule, count in issue_rows],
            "duplicates": sum(count - 1 for _, count in duplicate_rows),
            "message_lengths": buckets,
            "sources": [{"name": name, "count": count} for name, count in source_rows],
            "exportable_count": exportable_count or 0,
            "origins": {
                "original": max(0, (original_count or 0) - distilled_count),
                "augmented": augmented_count or 0,
                "distilled": distilled_count,
            },
        }
