"""Character length, paragraph, and Markdown heading splitters."""

import re
from dataclasses import dataclass
from typing import Protocol

from dataset_builder.models import Chunk, SourceDocument
from dataset_builder.parsers.text import markdown_headings


class Splitter(Protocol):
    def split(self, document: SourceDocument) -> list[Chunk]: ...


def _chunks(document: SourceDocument, pieces: list[tuple[str, dict[str, object]]]) -> list[Chunk]:
    source_metadata: dict[str, object] = {"source_name": document.source_name, "source_type": document.source_type}
    if "record_index" in document.metadata:
        source_metadata["record_index"] = document.metadata["record_index"]
    return [
        Chunk(
            document_id=document.id,
            index=index,
            content=content,
            metadata={**source_metadata, **metadata},
        )
        for index, (content, metadata) in enumerate(pieces)
        if content
    ]


def _window(content: str, max_length: int, overlap: int) -> list[str]:
    if not content:
        return []
    step = max_length - overlap
    pieces = []
    for start in range(0, len(content), step):
        pieces.append(content[start:start + max_length])
        if start + max_length >= len(content):
            break
    return pieces


@dataclass(frozen=True)
class FixedLengthSplitter:
    max_length: int
    overlap: int = 0

    def __post_init__(self) -> None:
        if self.max_length < 1 or not 0 <= self.overlap < self.max_length:
            raise ValueError("max_length must be positive and overlap must be smaller than max_length")

    def split(self, document: SourceDocument) -> list[Chunk]:
        return _chunks(document, [(piece, {}) for piece in _window(document.content, self.max_length, self.overlap)])


@dataclass(frozen=True)
class ParagraphSplitter(FixedLengthSplitter):
    def split(self, document: SourceDocument) -> list[Chunk]:
        paragraphs = [part.strip() for part in re.split(r"\n[ \t]*\n+", document.content) if part.strip()]
        pieces: list[str] = []
        current = ""
        for paragraph in paragraphs:
            candidate = f"{current}\n\n{paragraph}" if current else paragraph
            if len(candidate) <= self.max_length:
                current = candidate
                continue
            if current:
                pieces.append(current)
                current = ""
            if len(paragraph) > self.max_length:
                pieces.extend(_window(paragraph, self.max_length, self.overlap))
            else:
                current = paragraph
        if current:
            pieces.append(current)
        if self.overlap:
            for index in range(1, len(pieces)):
                available = min(self.overlap, self.max_length - len(pieces[index]))
                pieces[index] = pieces[index - 1][-available:] + pieces[index] if available else pieces[index]
        return _chunks(document, [(piece, {}) for piece in pieces])


@dataclass(frozen=True)
class MarkdownHeadingSplitter(FixedLengthSplitter):
    def split(self, document: SourceDocument) -> list[Chunk]:
        headings = markdown_headings(document.content)
        if not headings:
            return ParagraphSplitter(self.max_length, self.overlap).split(document)

        pieces: list[tuple[str, dict[str, object]]] = []
        active: list[str] = []
        boundaries = [0, *(int(item["offset"]) for item in headings), len(document.content)]
        if boundaries[0] == boundaries[1]:
            boundaries.pop(0)
        for index in range(len(boundaries) - 1):
            start, end = boundaries[index:index + 2]
            heading = next((item for item in headings if item["offset"] == start), None)
            if heading:
                level = int(heading["level"])
                active = active[:level - 1] + [str(heading["title"])]
            section = document.content[start:end].strip()
            metadata: dict[str, object] = {"heading_path": active.copy()} if active else {}
            pieces.extend((part, metadata.copy()) for part in _window(section, self.max_length, self.overlap))
        return _chunks(document, pieces)
