import json
from uuid import uuid4

import pytest

from dataset_builder.parsers import CSVParser, ImportSource, JSONLParser, JSONParser


@pytest.mark.parametrize("workers", [1, 4])
def test_json_parser_maps_nested_content_in_object_and_array(tmp_path, workers: int) -> None:
    path = tmp_path / "items.json"
    path.write_text(json.dumps([
        {"article": {"body": "第一段"}, "id": 1},
        {"article": {"body": "第二段"}, "id": 2},
    ]), encoding="utf-8")
    project_id = uuid4()

    documents = JSONParser().parse(ImportSource(path, project_id, content_field="article.body", workers=workers))

    assert [document.content for document in documents] == ["第一段", "第二段"]
    assert [document.metadata["record_index"] for document in documents] == [0, 1]
    assert all(document.project_id == project_id and document.source_type == "json" for document in documents)
    assert all(document.metadata["file_size"] == path.stat().st_size for document in documents)


def test_json_parser_supports_single_object(tmp_path) -> None:
    path = tmp_path / "one.json"
    path.write_text('{"text": "Hello"}', encoding="utf-8")

    documents = JSONParser().parse(ImportSource(path, uuid4(), content_field="text"))

    assert len(documents) == 1
    assert documents[0].content == "Hello"


@pytest.mark.parametrize("workers", [1, 4])
def test_jsonl_parser_keeps_line_numbers_and_skips_blank_lines(tmp_path, workers: int) -> None:
    path = tmp_path / "items.jsonl"
    path.write_text('\ufeff{"text": "One"}\n\n{"text": "Two"}\n', encoding="utf-8")

    documents = JSONLParser().parse(ImportSource(path, uuid4(), content_field="text", workers=workers))

    assert [document.content for document in documents] == ["One", "Two"]
    assert [document.metadata["record_index"] for document in documents] == [1, 3]


@pytest.mark.parametrize("workers", [1, 4])
def test_csv_parser_uses_selected_columns_in_order(tmp_path, workers: int) -> None:
    path = tmp_path / "items.csv"
    path.write_text("title,body,ignored\nGreeting,Hello,x\nFarewell,Goodbye,y\n", encoding="utf-8")

    documents = CSVParser().parse(ImportSource(path, uuid4(), content_columns=("title", "body"), workers=workers))

    assert [document.content for document in documents] == [
        "title: Greeting\nbody: Hello", "title: Farewell\nbody: Goodbye"
    ]
    assert [document.metadata["record_index"] for document in documents] == [2, 3]
    assert all(document.source_type == "csv" for document in documents)


@pytest.mark.parametrize("parser_class,filename,contents,options,match", [
    (JSONParser, "bad.json", '{"other":"x"}', {"content_field": "text"}, "Record 0"),
    (JSONParser, "bad.json", '{"text":7}', {"content_field": "text"}, "must be a string"),
    (JSONLParser, "bad.jsonl", '{invalid}', {"content_field": "text"}, "第 1 行"),
    (CSVParser, "bad.csv", "title,body\nA,B\n", {"content_columns": ("missing",)}, "no columns"),
])
@pytest.mark.parametrize("workers", [1, 4])
def test_structured_parsers_report_mapping_errors(
    tmp_path, parser_class, filename, contents, options, match, workers: int,
) -> None:
    path = tmp_path / filename
    path.write_text(contents, encoding="utf-8")

    with pytest.raises(ValueError, match=match):
        parser_class().parse(ImportSource(path, uuid4(), workers=workers, **options))


def test_structured_parsers_require_explicit_mapping(tmp_path) -> None:
    json_path = tmp_path / "items.json"
    json_path.write_text('{"content":"x"}', encoding="utf-8")
    csv_path = tmp_path / "items.csv"
    csv_path.write_text("content\nx\n", encoding="utf-8")

    with pytest.raises(ValueError, match="content-field"):
        JSONParser().parse(ImportSource(json_path, uuid4()))
    with pytest.raises(ValueError, match="content-column"):
        CSVParser().parse(ImportSource(csv_path, uuid4()))
