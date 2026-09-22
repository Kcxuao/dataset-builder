"""Review and edit unified samples while preserving validation history."""

from uuid import UUID

from sqlalchemy import Text, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from dataset_builder.application.preferences import PreferenceService
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
        rows = (
            await self.session.scalars(
                select(TrainingSampleRow)
                .where(TrainingSampleRow.project_id == project_id, TrainingSampleRow.superseded_at.is_(None))
                .order_by(TrainingSampleRow.created_at, TrainingSampleRow.id)
                .limit(limit)
                .offset(offset)
            )
        ).all()
        return [await self._view(row) for row in rows]

    async def search_samples(self, project_id: UUID, page: int, size: int, **filters: object) -> dict[str, object]:
        if page < 1 or not 1 <= size <= 200:
            raise ValueError("page 必须大于零，size 必须在 1 到 200 之间")
        project = await self.session.get(ProjectRow, project_id)
        if project is None or project.deleted_at is not None:
            raise LookupError("数据集不存在")
        conditions = [TrainingSampleRow.project_id == project_id, TrainingSampleRow.superseded_at.is_(None)]
        columns = (
            ("review_status", TrainingSampleRow.review_status),
            ("validation_status", TrainingSampleRow.validation_status),
            ("is_deleted", TrainingSampleRow.is_deleted),
            ("source_document_id", TrainingSampleRow.document_id),
        )
        for name, column in columns:
            if filters.get(name) is not None:
                conditions.append(column == filters[name])
        if issue_rule := filters.get("issue_rule"):
            issue_samples = select(ValidationIssueRow.sample_id).where(ValidationIssueRow.rule == issue_rule)
            conditions.append(TrainingSampleRow.id.in_(issue_samples))
        if keyword := filters.get("keyword"):
            conditions.append(TrainingSampleRow.messages.cast(Text).ilike(f"%{str(keyword).strip()}%"))
        query = (
            select(TrainingSampleRow).where(*conditions).order_by(TrainingSampleRow.created_at, TrainingSampleRow.id)
        )
        total = await self.session.scalar(select(func.count()).select_from(query.subquery()))
        rows = (await self.session.scalars(query.limit(size).offset((page - 1) * size))).all()
        return {"items": [await self._view(row) for row in rows], "total": total or 0, "page": page, "size": size}

    async def get_sample(self, sample_id: UUID) -> dict[str, object]:
        row = await self._row(sample_id)
        return await self._view(row)

    async def distillation_queue(
        self,
        project_id: UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, object]:
        if not 1 <= limit <= 200 or offset < 0:
            raise ValueError("limit 必须在 1 到 200 之间，offset 不能为负数")
        project = await self.session.get(ProjectRow, project_id)
        if project is None or project.deleted_at is not None:
            raise LookupError("数据集不存在")
        rows = (
            await self.session.scalars(
                select(TrainingSampleRow)
                .where(
                    TrainingSampleRow.project_id == project_id,
                    TrainingSampleRow.review_status == "pending",
                    TrainingSampleRow.validation_status == "passed",
                    TrainingSampleRow.is_deleted.is_(False),
                    TrainingSampleRow.superseded_at.is_(None),
                )
                .order_by(TrainingSampleRow.created_at, TrainingSampleRow.id)
            )
        ).all()
        candidates = [row for row in rows if row.metadata_.get("generator") == "distillation"]
        selected = candidates[offset : offset + limit]
        return {
            "items": [await self._distillation_comparison(row) for row in selected],
            "total": len(candidates),
            "limit": limit,
            "offset": offset,
        }

    async def decide_distillation(self, sample_id: UUID, decision: str) -> dict[str, object]:
        if decision not in {"adopt_teacher", "keep_original", "keep_both"}:
            raise ValueError("蒸馏审核决策无效")
        row = await self._row(sample_id)
        if row.metadata_.get("generator") != "distillation":
            raise ValueError("当前样本不是蒸馏候选")
        if row.review_status != "pending":
            raise ValueError("当前蒸馏候选已经完成审核")
        source = await self._distillation_source(row)
        if source is None:
            raise ValueError("蒸馏候选缺少可追溯的原样本")
        if decision in {"adopt_teacher", "keep_both"}:
            self._check_approval(row, ReviewStatus.APPROVED)
            row.review_status = ReviewStatus.APPROVED.value
        else:
            row.review_status = ReviewStatus.REJECTED.value
        row.metadata_ = {**row.metadata_, "distillation_decision": decision}
        row.updated_at = utc_now()
        if decision == "adopt_teacher":
            source.superseded_at = utc_now()
            source.updated_at = utc_now()
        pair, skip_reason = await PreferenceService(self.session).create_from_distillation(row, source, decision)
        await self.session.flush()
        result = await self._distillation_comparison(row)
        result["preference_pair_id"] = str(pair.id) if pair else None
        result["preference_skip_reason"] = skip_reason
        return result

    async def edit(self, sample_id: UUID, messages: list[Message]) -> dict[str, object]:
        row = await self._row(sample_id)
        original = TrainingSample.model_validate(
            {
                "id": row.id,
                "project_id": row.project_id,
                "document_id": row.document_id,
                "chunk_id": row.chunk_id,
                "messages": messages,
                "metadata": row.metadata_,
            }
        )
        hashes = set(
            (
                await self.session.scalars(
                    select(TrainingSampleRow.content_hash).where(
                        TrainingSampleRow.project_id == row.project_id,
                        TrainingSampleRow.id != row.id,
                        TrainingSampleRow.validation_status == "passed",
                        TrainingSampleRow.is_deleted.is_(False),
                        TrainingSampleRow.content_hash.is_not(None),
                    )
                )
            ).all()
        )
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
            self.session.add(
                ValidationIssueRow(
                    id=issue.id,
                    sample_id=sample_id,
                    rule=issue.rule,
                    severity=issue.severity,
                    message=issue.message,
                )
            )
        await self.session.flush()
        return await self._view(row)

    async def set_review(self, sample_id: UUID, status: ReviewStatus) -> dict[str, object]:
        row = await self._row(sample_id)
        self._check_approval(row, status)
        row.review_status = status.value
        row.updated_at = utc_now()
        if status == ReviewStatus.APPROVED:
            await self._supersede_distillation_source(row)
        await self.session.flush()
        return await self._view(row)

    async def bulk_action(self, project_id: UUID, sample_ids: list[UUID], action: str) -> dict[str, object]:
        if not sample_ids or len(sample_ids) > 200:
            raise ValueError("一次只能操作 1 到 200 条样本")
        if action not in {"approved", "rejected", "pending", "delete", "restore"}:
            raise ValueError("批量操作类型无效")
        ids = list(dict.fromkeys(sample_ids))
        rows = (
            await self.session.scalars(
                select(TrainingSampleRow).where(
                    TrainingSampleRow.project_id == project_id, TrainingSampleRow.id.in_(ids)
                )
            )
        ).all()
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
                if action == "approved":
                    await self._supersede_distillation_source(row)
            row.updated_at = utc_now()
            updated.append(str(sample_id))
        await self.session.flush()
        return {"updated_ids": updated, "skipped": skipped}

    @staticmethod
    def _check_approval(row: TrainingSampleRow, status: ReviewStatus) -> None:
        if status == ReviewStatus.APPROVED and (row.validation_status != "passed" or row.is_deleted):
            raise ValueError("样本校验未通过或已删除，无法审核通过")

    async def _supersede_distillation_source(self, row: TrainingSampleRow) -> None:
        if row.metadata_.get("generator") != "distillation":
            return
        source_id = row.metadata_.get("distillation_source_id")
        if not source_id:
            return
        try:
            source_uuid = UUID(str(source_id))
        except ValueError:
            return
        source = await self.session.get(TrainingSampleRow, source_uuid)
        if source is not None and source.project_id == row.project_id:
            source.superseded_at = utc_now()
            source.updated_at = utc_now()

    async def _distillation_source(self, row: TrainingSampleRow) -> TrainingSampleRow | None:
        source_id = row.metadata_.get("distillation_source_id")
        if not source_id:
            return None
        try:
            source_uuid = UUID(str(source_id))
        except ValueError:
            return None
        source = await self.session.get(TrainingSampleRow, source_uuid)
        if source is None or source.project_id != row.project_id:
            return None
        return source

    async def _distillation_comparison(self, row: TrainingSampleRow) -> dict[str, object]:
        source = await self._distillation_source(row)
        chunk = await self.session.get(ChunkRow, row.chunk_id)
        return {
            "id": str(row.id),
            "source_sample_id": str(source.id) if source else None,
            "source_messages": source.messages if source else [],
            "candidate_messages": row.messages,
            "chunk_content": chunk.content if chunk else None,
            "review_status": row.review_status,
            "validation_status": row.validation_status,
            "decision": row.metadata_.get("distillation_decision"),
        }

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
        issues = (
            await self.session.scalars(
                select(ValidationIssueRow)
                .where(ValidationIssueRow.sample_id == row.id)
                .order_by(ValidationIssueRow.created_at)
            )
        ).all()
        return {
            "id": str(row.id),
            "project_id": str(row.project_id),
            "chunk_id": str(row.chunk_id),
            "messages": row.messages,
            "metadata": row.metadata_,
            "chunk_content": chunk.content if chunk else None,
            "review_status": row.review_status,
            "validation_status": row.validation_status,
            "is_deleted": row.is_deleted,
            "superseded_at": row.superseded_at,
            "parent_sample_id": str(row.parent_sample_id) if row.parent_sample_id else None,
            "generation_run_id": str(row.generation_run_id) if row.generation_run_id else None,
            "distillation_source_id": row.metadata_.get("distillation_source_id"),
            "issues": [{"rule": issue.rule, "severity": issue.severity, "message": issue.message} for issue in issues],
        }
