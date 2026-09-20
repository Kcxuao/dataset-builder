"""Soft deletion and restoration of dataset projects."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from dataset_builder.db.orm import ProjectRow
from dataset_builder.models import utc_now


class ProjectService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_active(self, project_id: UUID) -> ProjectRow:
        row = await self.session.get(ProjectRow, project_id)
        if row is None or row.deleted_at is not None:
            raise LookupError("数据集不存在")
        return row

    async def move_to_trash(self, project_id: UUID) -> ProjectRow:
        row = await self.get_active(project_id)
        row.deleted_at = utc_now()
        await self.session.flush()
        return row

    async def restore(self, project_id: UUID) -> ProjectRow:
        row = await self.session.get(ProjectRow, project_id)
        if row is None or row.deleted_at is None:
            raise LookupError("回收站中没有该数据集")
        row.deleted_at = None
        await self.session.flush()
        return row
