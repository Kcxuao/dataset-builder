"""Import Alpaca and ShareGPT records into the unified training-sample IR."""

import json
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from dataset_builder.cleaners import BasicCleaner
from dataset_builder.db.orm import ChunkRow, ProjectRow, SourceDocumentRow, TrainingSampleRow, ValidationIssueRow
from dataset_builder.models import Message, MessageRole, ParseStatus, TrainingSample
from dataset_builder.validators import SampleValidator


class TrainingImportService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.cleaner = BasicCleaner()
        self.validator = SampleValidator()

    async def import_files(self, files: list[tuple[str, bytes]], project_name: str) -> dict[str, object]:
        if not files or not project_name.strip():
            raise ValueError("请选择训练样本文件并填写数据集名称")
        project_id = uuid4()
        self.session.add(ProjectRow(id=project_id, name=project_name.strip()))
        await self.session.flush()
        seen: set[tuple[UUID, str]] = set()
        sample_count = 0
        for filename, raw in files:
            records = self._records(filename, raw)
            for line, record in records:
                messages = self._messages(record, filename, line)
                content = "\n".join(f"{message.role}: {message.content}" for message in messages)
                document_id, chunk_id = uuid4(), uuid4()
                metadata = {"source_name": filename, "source_type": "training_import", "line": line}
                document = SourceDocumentRow(
                    id=document_id,
                    project_id=project_id,
                    source_name=filename,
                    source_type="training_import",
                    content=content,
                    metadata_=metadata,
                    parse_status=ParseStatus.SUCCESS,
                )
                self.session.add(document)
                await self.session.flush([document])
                self.session.add(
                    ChunkRow(
                        id=chunk_id,
                        document_id=document_id,
                        index=0,
                        content=content,
                        metadata_=metadata,
                        generation_status="success",
                    )
                )
                original = TrainingSample(
                    project_id=project_id,
                    document_id=document_id,
                    chunk_id=chunk_id,
                    messages=messages,
                    metadata=metadata,
                )
                cleaned = self.cleaner.clean([original], seen)
                sample = (cleaned.accepted or cleaned.rejected)[0]
                issues = [*cleaned.issues, *self.validator.validate(sample)]
                self.session.add(
                    TrainingSampleRow(
                        id=sample.id,
                        project_id=project_id,
                        document_id=document_id,
                        chunk_id=chunk_id,
                        messages=[item.model_dump(mode="json") for item in sample.messages],
                        metadata_=sample.metadata,
                        content_hash=sample.content_hash,
                        review_status="pending",
                        validation_status="failed" if issues else "passed",
                        is_deleted=False,
                    )
                )
                for issue in issues:
                    self.session.add(
                        ValidationIssueRow(
                            id=issue.id,
                            sample_id=sample.id,
                            rule=issue.rule,
                            severity=issue.severity,
                            message=issue.message,
                        )
                    )
                if not issues and sample.content_hash:
                    seen.add((project_id, sample.content_hash))
                sample_count += 1
        await self.session.flush()
        return {"project_id": str(project_id), "sample_count": sample_count}

    @staticmethod
    def _records(filename: str, raw: bytes) -> list[tuple[int, object]]:
        try:
            if filename.lower().endswith(".jsonl"):
                return [
                    (line, json.loads(value))
                    for line, value in enumerate(raw.decode("utf-8-sig").splitlines(), 1)
                    if value.strip()
                ]
            value = json.loads(raw.decode("utf-8-sig"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{filename} 第 {exc.lineno} 行不是有效 JSON") from exc
        if not isinstance(value, list):
            value = [value]
        return list(enumerate(value, 1))

    @staticmethod
    def _messages(record: object, filename: str, line: int) -> list[Message]:
        if not isinstance(record, dict):
            raise ValueError(f"{filename} 第 {line} 条不是对象")
        if "instruction" in record and "output" in record:
            instruction, output = record["instruction"], record["output"]
            extra = record.get("input", "")
            if not all(isinstance(value, str) for value in (instruction, output, extra)):
                raise ValueError(f"{filename} 第 {line} 条 Alpaca 字段必须是字符串")
            user = instruction if not extra.strip() else f"{instruction}\n\n{extra}"
            return [Message(role=MessageRole.USER, content=user), Message(role=MessageRole.ASSISTANT, content=output)]
        conversations = record.get("conversations")
        if isinstance(conversations, list):
            roles = {"system": MessageRole.SYSTEM, "human": MessageRole.USER, "gpt": MessageRole.ASSISTANT}
            try:
                return [
                    Message(role=roles[item["from"]], content=item["value"])
                    for item in conversations
                    if isinstance(item, dict) and isinstance(item.get("value"), str)
                ]
            except KeyError as exc:
                raise ValueError(f"{filename} 第 {line} 条 ShareGPT 角色不受支持") from exc
        raise ValueError(f"{filename} 第 {line} 条不是 Alpaca 或 ShareGPT 格式")
