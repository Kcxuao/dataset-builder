"""TXT and Markdown parsers using the shared SourceDocument representation."""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import UUID

from dataset_builder.models import ParseStatus, SourceDocument

HEADING_PATTERN = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
FENCE_PATTERN = re.compile(r"^[ \t]*(`{3,}|~{3,})")


@dataclass(frozen=True)
class ImportSource:
    path: Path
    project_id: UUID
    content_field: str | None = None
    content_columns: tuple[str, ...] = ()
    workers: int = 1


class Parser(Protocol):
    def parse(self, source: ImportSource) -> list[SourceDocument]: ...


def markdown_headings(content: str) -> list[dict[str, object]]:
    """Find ATX headings outside fenced code blocks, with source offsets."""
    headings: list[dict[str, object]] = []
    fence_char = ""
    fence_size = 0
    offset = 0
    for line in content.splitlines(keepends=True):
        fence = FENCE_PATTERN.match(line)
        if fence:
            marker = fence.group(1)
            if not fence_char:
                fence_char, fence_size = marker[0], len(marker)
            elif marker[0] == fence_char and len(marker) >= fence_size:
                fence_char, fence_size = "", 0
        elif not fence_char:
            heading = HEADING_PATTERN.match(line.rstrip("\r\n"))
            if heading:
                headings.append({"level": len(heading.group(1)), "title": heading.group(2), "offset": offset})
        offset += len(line)
    return headings


class TextParser:
    source_type = "text"
    extensions = frozenset({".txt"})

    def parse(self, source: ImportSource) -> list[SourceDocument]:
        path = source.path
        if path.suffix.lower() not in self.extensions:
            raise ValueError(f"Unsupported {self.source_type} extension: {path.suffix}")
        raw = path.read_bytes()
        content = raw.decode("utf-8-sig")
        return [SourceDocument(
            project_id=source.project_id,
            source_name=path.name,
            source_type=self.source_type,
            content=content,
            metadata={"file_size": len(raw)},
            parse_status=ParseStatus.SUCCESS,
        )]


class MarkdownParser(TextParser):
    source_type = "markdown"
    extensions = frozenset({".md", ".markdown"})

    def parse(self, source: ImportSource) -> list[SourceDocument]:
        document = super().parse(source)[0]
        document.metadata["headings"] = markdown_headings(document.content)
        return [document]
