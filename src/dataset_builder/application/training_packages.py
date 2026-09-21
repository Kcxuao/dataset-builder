"""Create framework-ready packages from immutable dataset versions."""

from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dataset_builder.db.orm import DatasetVersionRow, DatasetVersionSampleRow, ProjectRow
from dataset_builder.formatters import ShareGPTFormatter
from dataset_builder.models import TrainingSample
from dataset_builder.training_targets import LLaMAFactoryConfig, LLaMAFactoryPackageBuilder


class TrainingPackageService:
    def __init__(self, session: AsyncSession, batch_size: int = 100) -> None:
        self.session = session
        self.batch_size = batch_size

    async def build_llamafactory(
        self, version_id: UUID, destination: Path, config: LLaMAFactoryConfig
    ) -> tuple[str, int]:
        version = await self.session.get(DatasetVersionRow, version_id)
        if version is None:
            raise LookupError("数据集版本不存在")
        project = await self.session.get(ProjectRow, version.project_id)
        if project is None or project.deleted_at is not None:
            raise LookupError("数据集不存在")

        async def records() -> AsyncIterator[dict[str, object]]:
            query = (
                select(DatasetVersionSampleRow)
                .where(DatasetVersionSampleRow.version_id == version_id)
                .order_by(DatasetVersionSampleRow.ordinal)
                .execution_options(yield_per=self.batch_size)
            )
            rows = await self.session.stream_scalars(query)
            try:
                async for row in rows:
                    sample = TrainingSample.model_validate({
                        "id": row.sample_id,
                        "project_id": version.project_id,
                        "document_id": row.document_id,
                        "chunk_id": row.chunk_id,
                        "messages": row.messages,
                        "metadata": row.metadata_,
                    })
                    yield ShareGPTFormatter().format(sample)
            finally:
                await rows.close()

        count = await LLaMAFactoryPackageBuilder().build(
            records(),
            destination,
            config,
            version_id=str(version.id),
            version_name=version.name,
            created_at=version.created_at,
        )
        return version.name, count
