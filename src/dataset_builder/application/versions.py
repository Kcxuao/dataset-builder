"""Create immutable dataset snapshots and compare their sample manifests."""

from __future__ import annotations

from collections import Counter
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dataset_builder.db.orm import (
    DatasetVersionPreferenceRow,
    DatasetVersionRow,
    DatasetVersionSampleRow,
    PreferencePairRow,
    ProjectRow,
    TrainingSampleRow,
)


class DatasetVersionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self, project_id: UUID, name: str, description: str | None = None, dataset_type: str = "sft"
    ) -> dict[str, object]:
        clean_name = name.strip()
        clean_description = description.strip() if description else None
        if not clean_name or len(clean_name) > 100:
            raise ValueError("版本名称不能为空且不能超过 100 个字符")
        if clean_description and len(clean_description) > 1000:
            raise ValueError("版本说明不能超过 1000 个字符")
        if dataset_type not in {"sft", "dpo"}:
            raise ValueError("数据集版本类型必须是 sft 或 dpo")
        project = await self.session.get(ProjectRow, project_id)
        if project is None or project.deleted_at is not None:
            raise LookupError("数据集不存在")
        duplicate = await self.session.scalar(select(DatasetVersionRow.id).where(
            DatasetVersionRow.project_id == project_id, DatasetVersionRow.name == clean_name
        ))
        if duplicate:
            raise ValueError("当前数据集已存在同名版本")
        if dataset_type == "dpo":
            pairs = (await self.session.scalars(
                select(PreferencePairRow).where(
                    PreferencePairRow.project_id == project_id,
                    PreferencePairRow.review_status == "approved",
                    PreferencePairRow.validation_status == "passed",
                    PreferencePairRow.is_deleted.is_(False),
                ).order_by(PreferencePairRow.id)
            )).all()
            if not pairs:
                raise ValueError("当前没有可发布的已审核 DPO 偏好对")
            version = DatasetVersionRow(
                id=uuid4(), project_id=project_id, name=clean_name, description=clean_description,
                dataset_type="dpo", sample_count=len(pairs),
                statistics={"origins": dict(Counter(pair.source_type for pair in pairs))},
            )
            self.session.add(version)
            await self.session.flush([version])
            self.session.add_all(DatasetVersionPreferenceRow(
                version_id=version.id, pair_id=pair.id, ordinal=index,
                context_messages=pair.context_messages, chosen_response=pair.chosen_response,
                rejected_response=pair.rejected_response, metadata_=pair.metadata_, content_hash=pair.content_hash,
            ) for index, pair in enumerate(pairs))
            await self.session.flush()
            return self._view(version)
        samples = (await self.session.scalars(
            select(TrainingSampleRow).where(
                TrainingSampleRow.project_id == project_id,
                TrainingSampleRow.review_status == "approved",
                TrainingSampleRow.validation_status == "passed",
                TrainingSampleRow.is_deleted.is_(False),
                TrainingSampleRow.superseded_at.is_(None),
            ).order_by(TrainingSampleRow.id)
        )).all()
        if not samples:
            raise ValueError("当前没有可发布的已审核样本")
        origins = Counter(self._origin(sample) for sample in samples)
        version = DatasetVersionRow(
            id=uuid4(),
            project_id=project_id,
            name=clean_name,
            description=clean_description,
            dataset_type="sft",
            sample_count=len(samples),
            statistics={"origins": dict(origins)},
        )
        self.session.add(version)
        await self.session.flush([version])
        self.session.add_all(
            DatasetVersionSampleRow(
                version_id=version.id,
                sample_id=sample.id,
                document_id=sample.document_id,
                chunk_id=sample.chunk_id,
                ordinal=index,
                messages=sample.messages,
                metadata_=sample.metadata_,
                content_hash=sample.content_hash,
            )
            for index, sample in enumerate(samples)
        )
        await self.session.flush()
        return self._view(version)

    async def list(self, project_id: UUID) -> list[dict[str, object]]:
        project = await self.session.get(ProjectRow, project_id)
        if project is None or project.deleted_at is not None:
            raise LookupError("数据集不存在")
        rows = (await self.session.scalars(
            select(DatasetVersionRow)
            .where(DatasetVersionRow.project_id == project_id)
            .order_by(DatasetVersionRow.created_at.desc(), DatasetVersionRow.id.desc())
        )).all()
        return [self._view(row) for row in rows]

    async def compare(self, project_id: UUID, base_id: UUID, target_id: UUID) -> dict[str, object]:
        base = await self._version(project_id, base_id)
        target = await self._version(project_id, target_id)
        if base.dataset_type != target.dataset_type:
            raise ValueError("不能比较不同类型的数据集版本")
        if base.dataset_type == "dpo":
            base_rows = await self._preferences(base.id)
            target_rows = await self._preferences(target.id)
            return self._preference_comparison(base, target, base_rows, target_rows)
        base_rows = await self._samples(base.id)
        target_rows = await self._samples(target.id)
        return self._comparison(base, target, base_rows, target_rows)

    async def get(self, project_id: UUID, version_id: UUID) -> dict[str, object]:
        return self._view(await self._version(project_id, version_id))

    async def _version(self, project_id: UUID, version_id: UUID) -> DatasetVersionRow:
        row = await self.session.get(DatasetVersionRow, version_id)
        if row is None or row.project_id != project_id:
            raise LookupError("数据集版本不存在")
        return row

    async def _samples(self, version_id: UUID) -> list[DatasetVersionSampleRow]:
        return (await self.session.scalars(
            select(DatasetVersionSampleRow)
            .where(DatasetVersionSampleRow.version_id == version_id)
            .order_by(DatasetVersionSampleRow.ordinal)
        )).all()

    async def _preferences(self, version_id: UUID) -> list[DatasetVersionPreferenceRow]:
        return (await self.session.scalars(
            select(DatasetVersionPreferenceRow).where(DatasetVersionPreferenceRow.version_id == version_id)
            .order_by(DatasetVersionPreferenceRow.ordinal)
        )).all()

    @staticmethod
    def _preference_comparison(base, target, base_rows, target_rows) -> dict[str, object]:
        base_by_id = {row.pair_id: row for row in base_rows}
        target_by_id = {row.pair_id: row for row in target_rows}
        added = [row for row in target_rows if row.pair_id not in base_by_id]
        removed = [row for row in base_rows if row.pair_id not in target_by_id]
        changed = [
            row
            for row in target_rows
            if row.pair_id in base_by_id and row.content_hash != base_by_id[row.pair_id].content_hash
        ]

        def summary(row: DatasetVersionPreferenceRow) -> dict[str, str]:
            return {"pair_id": str(row.pair_id), "excerpt": row.context_messages[-1]["content"][:160]}
        return {
            "base": DatasetVersionService._view(base), "target": DatasetVersionService._view(target),
            "counts": {"added": len(added), "removed": len(removed), "changed": len(changed), "replaced": 0},
            "added": [summary(row) for row in added], "removed": [summary(row) for row in removed],
            "changed": [summary(row) for row in changed],
        }

    @staticmethod
    def _comparison(
        base: DatasetVersionRow,
        target: DatasetVersionRow,
        base_rows: list[DatasetVersionSampleRow],
        target_rows: list[DatasetVersionSampleRow],
    ) -> dict[str, object]:
        base_by_id = {row.sample_id: row for row in base_rows}
        target_by_id = {row.sample_id: row for row in target_rows}
        added = [row for row in target_rows if row.sample_id not in base_by_id]
        removed = [row for row in base_rows if row.sample_id not in target_by_id]
        changed = [
            row for row in target_rows
            if row.sample_id in base_by_id and row.content_hash != base_by_id[row.sample_id].content_hash
        ]
        removed_ids = {row.sample_id for row in removed}
        replacements = [
            row for row in added
            if DatasetVersionService._metadata_uuid(row.metadata_, "distillation_source_id") in removed_ids
        ]
        return {
            "base": DatasetVersionService._view(base),
            "target": DatasetVersionService._view(target),
            "counts": {
                "added": len(added),
                "removed": len(removed),
                "changed": len(changed),
                "replaced": len(replacements),
            },
            "added": [DatasetVersionService._sample_summary(row) for row in added],
            "removed": [DatasetVersionService._sample_summary(row) for row in removed],
            "changed": [DatasetVersionService._sample_summary(row) for row in changed],
        }

    @staticmethod
    def _metadata_uuid(metadata: dict, key: str) -> UUID | None:
        try:
            return UUID(str(metadata.get(key))) if metadata.get(key) else None
        except ValueError:
            return None

    @staticmethod
    def _sample_summary(row: DatasetVersionSampleRow) -> dict[str, object]:
        user = next((message["content"] for message in row.messages if message["role"] == "user"), "空消息")
        return {"sample_id": str(row.sample_id), "excerpt": user[:160], "origin": DatasetVersionService._origin(row)}

    @staticmethod
    def _origin(row: TrainingSampleRow | DatasetVersionSampleRow) -> str:
        generator = row.metadata_.get("generator")
        if generator == "distillation":
            return "distillation"
        if generator == "augmentation" or row.metadata_.get("parent_sample_id"):
            return "augmentation"
        return "original"

    @staticmethod
    def _view(row: DatasetVersionRow) -> dict[str, object]:
        return {
            "id": str(row.id),
            "project_id": str(row.project_id),
            "name": row.name,
            "description": row.description,
            "dataset_type": row.dataset_type,
            "sample_count": row.sample_count,
            "statistics": row.statistics,
            "created_at": row.created_at,
        }
