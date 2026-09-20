from uuid import uuid4

import pytest

from dataset_builder.models import SourceDocument
from dataset_builder.parsers import MarkdownParser, TextParser
from dataset_builder.parsers.text import ImportSource
from dataset_builder.splitters import FixedLengthSplitter, MarkdownHeadingSplitter, ParagraphSplitter


def test_text_parser_records_source_and_file_size(tmp_path) -> None:
    path = tmp_path / "notes.txt"
    path.write_bytes("\ufeff第一段\n\n第二段".encode())
    project_id = uuid4()

    document = TextParser().parse(ImportSource(path=path, project_id=project_id))[0]

    assert document.project_id == project_id
    assert document.source_name == "notes.txt"
    assert document.source_type == "text"
    assert document.content == "第一段\n\n第二段"
    assert document.metadata["file_size"] == path.stat().st_size
    assert document.parse_status == "success"


def test_markdown_parser_preserves_heading_structure_outside_fences(tmp_path) -> None:
    path = tmp_path / "guide.md"
    path.write_text("# Intro\nText\n```md\n# Not a heading\n```\n## Details\nMore", encoding="utf-8")

    document = MarkdownParser().parse(ImportSource(path=path, project_id=uuid4()))[0]

    assert [(item["level"], item["title"]) for item in document.metadata["headings"]] == [
        (1, "Intro"), (2, "Details")
    ]
    assert "# Not a heading" in document.content


def test_parser_rejects_wrong_extension_and_invalid_utf8(tmp_path) -> None:
    wrong = tmp_path / "notes.md"
    wrong.write_text("hello")
    with pytest.raises(ValueError, match="Unsupported"):
        TextParser().parse(ImportSource(path=wrong, project_id=uuid4()))

    bad = tmp_path / "bad.txt"
    bad.write_bytes(b"\xff")
    with pytest.raises(UnicodeDecodeError):
        TextParser().parse(ImportSource(path=bad, project_id=uuid4()))


def test_fixed_splitter_respects_overlap_length_and_lineage() -> None:
    document = SourceDocument(project_id=uuid4(), source_name="x.txt", source_type="text", content="abcdefghij")

    chunks = FixedLengthSplitter(max_length=6, overlap=2).split(document)

    assert [chunk.content for chunk in chunks] == ["abcdef", "efghij"]
    assert [chunk.index for chunk in chunks] == [0, 1]
    assert all(chunk.document_id == document.id for chunk in chunks)
    assert chunks[0].metadata["source_name"] == "x.txt"


def test_paragraph_splitter_groups_paragraphs_and_limits_long_ones() -> None:
    document = SourceDocument(
        project_id=uuid4(), source_name="x.txt", source_type="text", content="One\n\nTwo\n\nabcdefghij"
    )

    chunks = ParagraphSplitter(max_length=8).split(document)

    assert [chunk.content for chunk in chunks] == ["One\n\nTwo", "abcdefgh", "ij"]
    assert all(len(chunk.content) <= 8 for chunk in chunks)


def test_paragraph_splitter_adds_overlap_when_space_allows() -> None:
    document = SourceDocument(
        project_id=uuid4(), source_name="x.txt", source_type="text", content="Alpha\n\nBravo"
    )

    chunks = ParagraphSplitter(max_length=8, overlap=2).split(document)

    assert [chunk.content for chunk in chunks] == ["Alpha", "haBravo"]


def test_markdown_splitter_tracks_heading_path_and_chunk_limit(tmp_path) -> None:
    path = tmp_path / "guide.md"
    path.write_text("# Intro\nHello\n## Detail\nabcdefghijk\n# End\nBye", encoding="utf-8")
    document = MarkdownParser().parse(ImportSource(path=path, project_id=uuid4()))[0]

    chunks = MarkdownHeadingSplitter(max_length=15).split(document)

    assert [chunk.metadata["heading_path"] for chunk in chunks] == [
        ["Intro"], ["Intro", "Detail"], ["Intro", "Detail"], ["End"]
    ]
    assert all(len(chunk.content) <= 15 for chunk in chunks)
    assert [chunk.index for chunk in chunks] == list(range(len(chunks)))


def test_splitter_rejects_invalid_limits() -> None:
    with pytest.raises(ValueError):
        FixedLengthSplitter(max_length=0)
    with pytest.raises(ValueError):
        ParagraphSplitter(max_length=5, overlap=5)
