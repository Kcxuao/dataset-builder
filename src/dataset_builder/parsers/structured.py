"""Field-mapped JSON, JSONL, and CSV source parsers."""

import csv
import json

from dataset_builder.models import ParseStatus, SourceDocument
from dataset_builder.parsers.text import ImportSource


def _content_field(source: ImportSource) -> tuple[str, ...]:
    if not source.content_field or not source.content_field.strip():
        raise ValueError("JSON and JSONL imports require --content-field")
    parts = tuple(part.strip() for part in source.content_field.split("."))
    if any(not part for part in parts):
        raise ValueError("Content field path cannot contain empty segments")
    return parts


def _mapped_text(record: object, parts: tuple[str, ...], row: int) -> str:
    value = record
    for part in parts:
        if not isinstance(value, dict) or part not in value:
            raise ValueError(f"Record {row} has no content field {'.'.join(parts)!r}")
        value = value[part]
    if not isinstance(value, str):
        raise ValueError(f"Record {row} content field must be a string")
    return value


def _document(source: ImportSource, content: str, source_type: str, row: int, file_size: int) -> SourceDocument:
    return SourceDocument(
        project_id=source.project_id,
        source_name=source.path.name,
        source_type=source_type,
        content=content,
        metadata={"file_size": file_size, "record_index": row},
        parse_status=ParseStatus.SUCCESS,
    )


class JSONParser:
    def parse(self, source: ImportSource) -> list[SourceDocument]:
        if source.path.suffix.lower() != ".json":
            raise ValueError(f"Unsupported JSON extension: {source.path.suffix}")
        parts = _content_field(source)
        raw = source.path.read_bytes()
        data = json.loads(raw.decode("utf-8-sig"))
        records = data if isinstance(data, list) else [data]
        if not isinstance(data, (dict, list)):
            raise ValueError("JSON root must be an object or an array of objects")
        return [
            _document(source, _mapped_text(record, parts, index), "json", index, len(raw))
            for index, record in enumerate(records)
        ]


class JSONLParser:
    def parse(self, source: ImportSource) -> list[SourceDocument]:
        if source.path.suffix.lower() != ".jsonl":
            raise ValueError(f"Unsupported JSONL extension: {source.path.suffix}")
        parts = _content_field(source)
        file_size = source.path.stat().st_size
        documents: list[SourceDocument] = []
        with source.path.open("r", encoding="utf-8-sig") as input_file:
            for line_number, line in enumerate(input_file, start=1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"JSONL line {line_number} contains invalid JSON") from exc
                documents.append(_document(
                    source, _mapped_text(record, parts, line_number), "jsonl", line_number, file_size
                ))
        return documents


class CSVParser:
    def parse(self, source: ImportSource) -> list[SourceDocument]:
        if source.path.suffix.lower() != ".csv":
            raise ValueError(f"Unsupported CSV extension: {source.path.suffix}")
        columns = tuple(column.strip() for column in source.content_columns)
        if not columns or any(not column for column in columns):
            raise ValueError("CSV imports require one or more --content-column values")
        file_size = source.path.stat().st_size
        documents: list[SourceDocument] = []
        with source.path.open("r", encoding="utf-8-sig", newline="") as input_file:
            reader = csv.DictReader(input_file)
            missing = [column for column in columns if column not in (reader.fieldnames or [])]
            if missing:
                raise ValueError(f"CSV has no columns: {', '.join(missing)}")
            for row_number, row in enumerate(reader, start=2):
                content = "\n".join(f"{column}: {row[column] or ''}" for column in columns)
                documents.append(_document(source, content, "csv", row_number, file_size))
        return documents
