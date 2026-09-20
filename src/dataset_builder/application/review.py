"""Review and edit unified samples while preserving validation history."""

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from dataset_builder.cleaners import BasicCleaner
from dataset_builder.db.orm import ChunkRow, ProjectRow, TrainingSampleRow, ValidationIssueRow
from dataset_builder.models import Message, ReviewStatus, TrainingSample, utc_now
from dataset_builder.validators import SampleValidator


class ReviewService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.cleaner = BasicCleaner()
        self.validator = SampleValidator()

    async def list_samples(self, project_id: UUID, limit: int = 50, offset: int = 0) -> list[dict[str, object]]:
        if limit < 1 or offset < 0:
            raise ValueError("limit must be positive and offset nonnegative")
        project = await self.session.get(ProjectRow, project_id)
        if project is None or project.deleted_at is not None:
            raise LookupError("数据集不存在")
        rows = (await self.session.scalars(
            select(TrainingSampleRow)
            .where(TrainingSampleRow.project_id == project_id)
            .order_by(TrainingSampleRow.created_at, TrainingSampleRow.id)
            .limit(limit).offset(offset)
        )).all()
        return [await self._view(row) for row in rows]

    async def get_sample(self, sample_id: UUID) -> dict[str, object]:
        row = await self._row(sample_id)
        return await self._view(row)

    async def edit(self, sample_id: UUID, messages: list[Message]) -> dict[str, object]:
        row = await self._row(sample_id)
        original = TrainingSample.model_validate({
            "id": row.id, "project_id": row.project_id, "document_id": row.document_id,
            "chunk_id": row.chunk_id, "messages": messages, "metadata": row.metadata_,
        })
        hashes = set((await self.session.scalars(
            select(TrainingSampleRow.content_hash).where(
                TrainingSampleRow.project_id == row.project_id,
                TrainingSampleRow.id != row.id,
                TrainingSampleRow.validation_status == "passed",
                TrainingSampleRow.is_deleted.is_(False),
                TrainingSampleRow.content_hash.is_not(None),
            )
        )).all())
        cleaned = self.cleaner.clean([original], {(row.project_id, value) for value in hashes})
        sample = (cleaned.accepted or cleaned.rejected)[0]
        issues = [*cleaned.issues, *self.validator.validate(sample)]
        row.messages = [message.model_dump(mode="json") for message in sample.messages]
        row.content_hash = sample.content_hash
        row.validation_status = "failed" if issues else "passed"
        row.review_status = "pending"
        row.updated_at = utc_now()
        await self.session.execute(delete(ValidationIssueRow).where(ValidationIssueRow.sample_id == sample_id))
        for issue in issues:
            self.session.add(ValidationIssueRow(
                id=issue.id, sample_id=sample_id, rule=issue.rule,
                severity=issue.severity, message=issue.message,
            ))
        await self.session.flush()
        return await self._view(row)

    async def set_review(self, sample_id: UUID, status: ReviewStatus) -> dict[str, object]:
        row = await self._row(sample_id)
        self._check_approval(row, status)
        row.review_status = status.value
        row.updated_at = utc_now()
        await self.session.flush()
        return await self._view(row)

    async def bulk_action(self, project_id: UUID, sample_ids: list[UUID], action: str) -> dict[str, object]:
        if not sample_ids or len(sample_ids) > 200:
            raise ValueError("一次只能操作 1 到 200 条样本")
        if action not in {"approved", "rejected", "pending", "delete", "restore"}:
            raise ValueError("批量操作类型无效")
        ids = list(dict.fromkeys(sample_ids))
        rows = (await self.session.scalars(
            select(TrainingSampleRow).where(
                TrainingSampleRow.project_id == project_id, TrainingSampleRow.id.in_(ids)
            )
        )).all()
        by_id = {row.id: row for row in rows}
        updated: list[str] = []
        skipped: list[dict[str, str]] = []
        for sample_id in ids:
            row = by_id.get(sample_id)
            if row is None:
                skipped.append({"id": str(sample_id), "reason": "样本不属于当前项目或不存在"})
                continue
            if action == "approved" and (row.validation_status != "passed" or row.is_deleted):
                skipped.append({"id": str(sample_id), "reason": "样本校验未通过或已删除，无法审核通过"})
                continue
            if action == "delete":
                row.is_deleted = True
            elif action == "restore":
                row.is_deleted = False
            else:
                row.review_status = action
            row.updated_at = utc_now()
            updated.append(str(sample_id))
        await self.session.flush()
        return {"updated_ids": updated, "skipped": skipped}

    @staticmethod
    def _check_approval(row: TrainingSampleRow, status: ReviewStatus) -> None:
        if status == ReviewStatus.APPROVED and (row.validation_status != "passed" or row.is_deleted):
            raise ValueError("样本校验未通过或已删除，无法审核通过")

    async def set_deleted(self, sample_id: UUID, deleted: bool) -> dict[str, object]:
        row = await self._row(sample_id)
        row.is_deleted = deleted
        row.updated_at = utc_now()
        await self.session.flush()
        return await self._view(row)

    async def _row(self, sample_id: UUID) -> TrainingSampleRow:
        row = await self.session.get(TrainingSampleRow, sample_id)
        if row is None:
            raise LookupError(f"Sample {sample_id} does not exist")
        project = await self.session.get(ProjectRow, row.project_id)
        if project is None or project.deleted_at is not None:
            raise LookupError("数据集不存在")
        return row

    async def _view(self, row: TrainingSampleRow) -> dict[str, object]:
        chunk = await self.session.get(ChunkRow, row.chunk_id)
        issues = (await self.session.scalars(
            select(ValidationIssueRow)
            .where(ValidationIssueRow.sample_id == row.id)
            .order_by(ValidationIssueRow.created_at)
        )).all()
        return {
            "id": str(row.id), "project_id": str(row.project_id), "chunk_id": str(row.chunk_id),
            "messages": row.messages, "metadata": row.metadata_, "chunk_content": chunk.content if chunk else None,
            "review_status": row.review_status, "validation_status": row.validation_status,
            "is_deleted": row.is_deleted,
            "issues": [{"rule": issue.rule, "severity": issue.severity, "message": issue.message} for issue in issues],
        }
