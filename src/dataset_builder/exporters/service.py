"""Stream eligible PostgreSQL samples through a formatter and file writer."""

from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dataset_builder.db.orm import ExportRecordRow, ProjectRow, TrainingSampleRow
from dataset_builder.exporters.files import JSONExporter, JSONLExporter
from dataset_builder.formatters import AlpacaFormatter, ShareGPTFormatter
from dataset_builder.models import ExportFileType, ExportFormat, ExportRecord, TrainingSample, utc_now


class SampleExportService:
    def __init__(self, session: AsyncSession, batch_size: int = 100) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        self.session = session
        self.batch_size = batch_size

    async def export(
        self,
        project_id: UUID,
        format: ExportFormat,
        file_type: ExportFileType,
        destination: Path,
    ) -> ExportRecord:
        project = await self.session.get(ProjectRow, project_id)
        if project is None or project.deleted_at is not None:
            raise LookupError("数据集不存在")
        formatter = AlpacaFormatter() if format == ExportFormat.ALPACA else ShareGPTFormatter()
        exporter = JSONLExporter() if file_type == ExportFileType.JSONL else JSONExporter()
        record = ExportRecordRow(
            project_id=project_id, format=format.value, file_type=file_type.value, status="pending"
        )
        self.session.add(record)

        async def formatted_records() -> AsyncIterator[dict[str, object]]:
            query = (
                select(TrainingSampleRow)
                .where(
                    TrainingSampleRow.project_id == project_id,
                    TrainingSampleRow.review_status == "approved",
                    TrainingSampleRow.validation_status == "passed",
                    TrainingSampleRow.is_deleted.is_(False),
                    TrainingSampleRow.superseded_at.is_(None),
                )
                .order_by(TrainingSampleRow.id)
                .execution_options(yield_per=self.batch_size)
            )
            rows = await self.session.stream_scalars(query)
            try:
                async for row in rows:
                    sample = TrainingSample.model_validate(
                        {
                            "id": row.id,
                            "project_id": row.project_id,
                            "document_id": row.document_id,
                            "chunk_id": row.chunk_id,
                            "messages": row.messages,
                            "metadata": row.metadata_,
                        }
                    )
                    yield formatter.format(sample)
            finally:
                await rows.close()

        try:
            record.sample_count = await exporter.export(formatted_records(), destination)
            record.file_path = str(destination)
            record.status = "completed"
        except Exception as exc:
            record.status = "failed"
            record.error_message = str(exc)
            raise
        finally:
            record.finished_at = utc_now()
            await self.session.flush()
        return ExportRecord.model_validate(
            {
                "id": record.id,
                "project_id": project_id,
                "format": format,
                "file_type": file_type,
                "status": record.status,
                "sample_count": record.sample_count,
                "file_path": record.file_path,
                "error_message": record.error_message,
                "created_at": record.created_at,
                "finished_at": record.finished_at,
            }
        )
