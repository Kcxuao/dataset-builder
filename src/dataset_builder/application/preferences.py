"""Create, validate, review, and backfill DPO preference pairs."""

from __future__ import annotations

import hashlib
import json
from uuid import UUID, uuid4

from sqlalchemy import Text, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from dataset_builder.db.orm import (
    PreferencePairRow,
    PreferenceValidationIssueRow,
    ProjectRow,
    TrainingSampleRow,
)
from dataset_builder.models import Message, ReviewStatus, utc_now


def preference_hash(context: list[dict], chosen: dict, rejected: dict) -> str:
    normalized = {
        "context": [{"role": item["role"], "content": item["content"].strip()} for item in context],
        "chosen": {"role": chosen["role"], "content": chosen["content"].strip()},
        "rejected": {"role": rejected["role"], "content": rejected["content"].strip()},
    }
    payload = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


class PreferenceValidator:
    def validate(self, context: list[dict], chosen: dict, rejected: dict) -> list[tuple[str, str]]:
        issues: list[tuple[str, str]] = []
        if not context:
            issues.append(("empty_context", "共同上下文不能为空"))
        else:
            roles = [item.get("role") for item in context]
            if any(role not in {"system", "user", "assistant"} for role in roles):
                issues.append(("invalid_role", "上下文包含不支持的消息角色"))
            if any(not str(item.get("content", "")).strip() for item in context):
                issues.append(("empty_content", "上下文消息内容不能为空"))
            if roles[-1] != "user":
                issues.append(("context_not_user", "共同上下文必须以 user 消息结束"))
            conversational = [role for role in roles if role != "system"]
            if any(role != ("user" if index % 2 == 0 else "assistant") for index, role in enumerate(conversational)):
                issues.append(("invalid_order", "共同上下文中的 user 和 assistant 顺序不正确"))
        for name, response in (("chosen", chosen), ("rejected", rejected)):
            if response.get("role") != "assistant":
                issues.append((f"{name}_role", f"{name} 必须是 assistant 消息"))
            if not str(response.get("content", "")).strip():
                issues.append((f"{name}_empty", f"{name} 回答不能为空"))
        if str(chosen.get("content", "")).strip() == str(rejected.get("content", "")).strip():
            issues.append(("identical_responses", "chosen 和 rejected 不能相同"))
        return issues


class PreferenceService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.validator = PreferenceValidator()

    async def create_manual(
        self,
        project_id: UUID,
        context_messages: list[Message],
        chosen_response: Message,
        rejected_response: Message,
        *,
        chosen_sample_id: UUID | None = None,
        rejected_sample_id: UUID | None = None,
    ) -> dict[str, object]:
        await self._active_project(project_id)
        context = [item.model_dump(mode="json") for item in context_messages]
        chosen = chosen_response.model_dump(mode="json")
        rejected = rejected_response.model_dump(mode="json")
        if chosen_sample_id or rejected_sample_id:
            if not chosen_sample_id or not rejected_sample_id:
                raise ValueError("选择现有样本时必须同时提供 chosen 和 rejected 样本")
            chosen_row, rejected_row = await self._sample_pair(project_id, chosen_sample_id, rejected_sample_id)
            context, chosen, rejected = self._extract_shared_pair(chosen_row.messages, rejected_row.messages)
        row = await self._insert(
            project_id,
            context,
            chosen,
            rejected,
            chosen_sample_id=chosen_sample_id,
            rejected_sample_id=rejected_sample_id,
            source_type="manual",
            review_status="pending",
        )
        return await self._view(row)

    async def create_from_distillation(
        self, candidate: TrainingSampleRow, source: TrainingSampleRow, decision: str
    ) -> tuple[PreferencePairRow | None, str | None]:
        if decision == "keep_both":
            return None, "两者保留不表达明确偏好"
        existing = await self.session.scalar(
            select(PreferencePairRow).where(PreferencePairRow.source_decision_id == candidate.id)
        )
        if existing:
            return existing, None
        try:
            if decision == "adopt_teacher":
                context, chosen, rejected = self._extract_shared_pair(candidate.messages, source.messages)
                chosen_id, rejected_id = candidate.id, source.id
            else:
                context, chosen, rejected = self._extract_shared_pair(source.messages, candidate.messages)
                chosen_id, rejected_id = source.id, candidate.id
        except ValueError as exc:
            return None, str(exc)
        try:
            row = await self._insert(
                candidate.project_id,
                context,
                chosen,
                rejected,
                chosen_sample_id=chosen_id,
                rejected_sample_id=rejected_id,
                document_id=candidate.document_id,
                chunk_id=candidate.chunk_id,
                source_type="distillation_review",
                source_decision_id=candidate.id,
                review_status="approved",
                metadata={"distillation_decision": decision},
            )
        except ValueError as exc:
            return None, str(exc)
        return row, None

    async def list(
        self,
        project_id: UUID,
        *,
        page: int = 1,
        size: int = 20,
        review_status: str | None = None,
        validation_status: str | None = None,
        source_type: str | None = None,
        keyword: str | None = None,
    ) -> dict[str, object]:
        await self._active_project(project_id)
        conditions = [PreferencePairRow.project_id == project_id, PreferencePairRow.is_deleted.is_(False)]
        if review_status:
            conditions.append(PreferencePairRow.review_status == review_status)
        if validation_status:
            conditions.append(PreferencePairRow.validation_status == validation_status)
        if source_type:
            conditions.append(PreferencePairRow.source_type == source_type)
        if keyword and keyword.strip():
            term = f"%{keyword.strip()}%"
            conditions.append(or_(
                PreferencePairRow.context_messages.cast(Text).ilike(term),
                PreferencePairRow.chosen_response.cast(Text).ilike(term),
                PreferencePairRow.rejected_response.cast(Text).ilike(term),
            ))
        total = await self.session.scalar(select(func.count()).select_from(PreferencePairRow).where(*conditions))
        rows = (await self.session.scalars(
            select(PreferencePairRow).where(*conditions)
            .order_by(PreferencePairRow.created_at.desc(), PreferencePairRow.id.desc())
            .offset((page - 1) * size).limit(size)
        )).all()
        return {"items": [await self._view(row) for row in rows], "total": total or 0, "page": page, "size": size}

    async def edit(
        self, pair_id: UUID, context_messages: list[Message], chosen_response: Message, rejected_response: Message
    ) -> dict[str, object]:
        row = await self._row(pair_id)
        context = [item.model_dump(mode="json") for item in context_messages]
        chosen, rejected = chosen_response.model_dump(mode="json"), rejected_response.model_dump(mode="json")
        row.context_messages, row.chosen_response, row.rejected_response = context, chosen, rejected
        row.content_hash = preference_hash(context, chosen, rejected)
        row.review_status, row.updated_at = "pending", utc_now()
        await self._validate_and_store(row)
        await self.session.flush()
        return await self._view(row)

    async def review(self, pair_id: UUID, status: ReviewStatus) -> dict[str, object]:
        row = await self._row(pair_id)
        if status == ReviewStatus.APPROVED and (row.validation_status != "passed" or row.is_deleted):
            raise ValueError("偏好对校验未通过或已删除，无法审核通过")
        row.review_status, row.updated_at = status.value, utc_now()
        await self.session.flush()
        return await self._view(row)

    async def set_deleted(self, pair_id: UUID, deleted: bool) -> dict[str, object]:
        row = await self._row(pair_id)
        row.is_deleted, row.updated_at = deleted, utc_now()
        await self.session.flush()
        return await self._view(row)

    async def backfill(self, project_id: UUID) -> dict[str, int]:
        await self._active_project(project_id)
        candidates = (await self.session.scalars(select(TrainingSampleRow).where(
            TrainingSampleRow.project_id == project_id,
            TrainingSampleRow.metadata_.cast(Text).ilike('%"distillation_decision"%'),
        ))).all()
        counts = {"created": 0, "existing": 0, "keep_both": 0, "invalid": 0}
        for candidate in candidates:
            decision = candidate.metadata_.get("distillation_decision")
            if decision == "keep_both":
                counts["keep_both"] += 1
                continue
            source_id = candidate.metadata_.get("distillation_source_id")
            try:
                source = await self.session.get(TrainingSampleRow, UUID(str(source_id))) if source_id else None
            except ValueError:
                source = None
            if source is None or decision not in {"adopt_teacher", "keep_original"}:
                counts["invalid"] += 1
                continue
            existed = await self.session.scalar(select(PreferencePairRow.id).where(
                PreferencePairRow.source_decision_id == candidate.id
            ))
            pair, reason = await self.create_from_distillation(candidate, source, decision)
            if reason:
                counts["invalid"] += 1
            elif existed:
                counts["existing"] += 1
            elif pair:
                counts["created"] += 1
        return counts

    async def _insert(
        self, project_id: UUID, context: list[dict], chosen: dict, rejected: dict, **values
    ) -> PreferencePairRow:
        digest = preference_hash(context, chosen, rejected)
        duplicate = await self.session.scalar(select(PreferencePairRow.id).where(
            PreferencePairRow.project_id == project_id, PreferencePairRow.content_hash == digest,
            PreferencePairRow.is_deleted.is_(False),
        ))
        if duplicate:
            raise ValueError("项目中已存在相同的偏好对")
        row = PreferencePairRow(
            id=uuid4(), project_id=project_id, context_messages=context, chosen_response=chosen,
            rejected_response=rejected, content_hash=digest, **values,
        )
        self.session.add(row)
        await self.session.flush([row])
        await self._validate_and_store(row)
        if row.review_status == "approved" and row.validation_status != "passed":
            row.review_status = "pending"
        await self.session.flush()
        return row

    async def _validate_and_store(self, row: PreferencePairRow) -> None:
        await self.session.execute(delete(PreferenceValidationIssueRow).where(
            PreferenceValidationIssueRow.pair_id == row.id
        ))
        issues = self.validator.validate(row.context_messages, row.chosen_response, row.rejected_response)
        self.session.add_all(PreferenceValidationIssueRow(
            pair_id=row.id, rule=rule, severity="error", message=message
        ) for rule, message in issues)
        row.validation_status = "failed" if issues else "passed"

    @staticmethod
    def _extract_shared_pair(
        chosen_messages: list[dict], rejected_messages: list[dict]
    ) -> tuple[list[dict], dict, dict]:
        if len(chosen_messages) < 2 or len(rejected_messages) < 2:
            raise ValueError("样本缺少共同上下文或最终回答")
        chosen_response, rejected_response = chosen_messages[-1], rejected_messages[-1]
        chosen_context, rejected_context = chosen_messages[:-1], rejected_messages[:-1]
        if chosen_response.get("role") != "assistant" or rejected_response.get("role") != "assistant":
            raise ValueError("样本必须以 assistant 回答结束")
        if chosen_context != rejected_context:
            raise ValueError("两条回答的共同上下文不一致")
        return chosen_context, chosen_response, rejected_response

    async def _sample_pair(self, project_id: UUID, chosen_id: UUID, rejected_id: UUID):
        chosen = await self.session.get(TrainingSampleRow, chosen_id)
        rejected = await self.session.get(TrainingSampleRow, rejected_id)
        if not chosen or not rejected or chosen.project_id != project_id or rejected.project_id != project_id:
            raise LookupError("选择的训练样本不存在或不属于当前数据集")
        return chosen, rejected

    async def _active_project(self, project_id: UUID) -> ProjectRow:
        row = await self.session.get(ProjectRow, project_id)
        if row is None or row.deleted_at is not None:
            raise LookupError("数据集不存在")
        return row

    async def _row(self, pair_id: UUID) -> PreferencePairRow:
        row = await self.session.get(PreferencePairRow, pair_id)
        if row is None:
            raise LookupError("偏好对不存在")
        await self._active_project(row.project_id)
        return row

    async def _view(self, row: PreferencePairRow) -> dict[str, object]:
        issues = (await self.session.scalars(select(PreferenceValidationIssueRow).where(
            PreferenceValidationIssueRow.pair_id == row.id
        ).order_by(PreferenceValidationIssueRow.created_at))).all()
        return {
            "id": str(row.id), "project_id": str(row.project_id), "context_messages": row.context_messages,
            "chosen_response": row.chosen_response, "rejected_response": row.rejected_response,
            "chosen_sample_id": str(row.chosen_sample_id) if row.chosen_sample_id else None,
            "rejected_sample_id": str(row.rejected_sample_id) if row.rejected_sample_id else None,
            "source_type": row.source_type, "review_status": row.review_status,
            "validation_status": row.validation_status, "is_deleted": row.is_deleted,
            "metadata": row.metadata_, "created_at": row.created_at,
            "issues": [{"rule": issue.rule, "severity": issue.severity, "message": issue.message} for issue in issues],
        }
