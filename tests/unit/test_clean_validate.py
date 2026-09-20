from uuid import UUID, uuid4

import pytest

from dataset_builder.cleaners import BasicCleaner, content_hash
from dataset_builder.models import ExportFormat, Message, TrainingSample
from dataset_builder.validators import SampleValidator


def sample(*messages: tuple[str, str], project_id: UUID | None = None) -> TrainingSample:
    return TrainingSample(
        project_id=project_id or uuid4(),
        document_id=uuid4(),
        chunk_id=uuid4(),
        messages=[Message(role=role, content=content) for role, content in messages],
    )


def test_cleaner_trims_and_deduplicates_within_project() -> None:
    project_id = uuid4()
    first = sample(("user", " Cafe\u0301 "), ("assistant", " Yes "), project_id=project_id)
    duplicate = sample(("user", "Café"), ("assistant", "Yes"), project_id=project_id)
    other_project = sample(("user", "Café"), ("assistant", "Yes"))

    result = BasicCleaner().clean([first, duplicate, other_project])

    assert [item.id for item in result.accepted] == [first.id, other_project.id]
    assert [item.id for item in result.rejected] == [duplicate.id]
    assert result.accepted[0].messages[0].content == "Café"
    assert result.accepted[0].content_hash == content_hash(duplicate)
    assert first.messages[0].content == " Cafe\u0301 "
    assert [(issue.sample_id, issue.rule) for issue in result.issues] == [(duplicate.id, "duplicate_content")]


def test_cleaner_rejects_empty_and_long_content_with_issues() -> None:
    blank = sample(("user", "  "), ("assistant", "A"))
    too_long = sample(("user", "abcd"), ("assistant", "A"))
    no_messages = sample()

    result = BasicCleaner(max_message_length=3).clean([blank, too_long, no_messages])

    assert result.accepted == []
    assert {issue.rule for issue in result.issues} == {
        "empty_content", "content_too_long", "empty_messages"
    }
    assert {item.id for item in result.rejected} == {blank.id, too_long.id, no_messages.id}


def test_cleaner_checks_existing_hashes_without_mutating_caller_set() -> None:
    original = sample(("user", "Q"), ("assistant", "A"))
    hashes = {(original.project_id, content_hash(original))}

    result = BasicCleaner().clean([original], existing_hashes=hashes)

    assert result.accepted == []
    assert result.issues[0].rule == "duplicate_content"
    assert hashes == {(original.project_id, content_hash(original))}


def test_validator_accepts_valid_single_and_multi_turn_sharegpt() -> None:
    validator = SampleValidator()
    single = sample(("user", "Q"), ("assistant", "A"))
    multi = sample(("system", "Guide"), ("user", "Q"), ("assistant", "A"), ("user", "Q2"), ("assistant", "A2"))

    assert validator.validate(single, ExportFormat.ALPACA) == []
    assert validator.validate(multi, ExportFormat.SHAREGPT) == []
    assert [issue.rule for issue in validator.validate(multi, ExportFormat.ALPACA)] == ["formatter_incompatible"]


@pytest.mark.parametrize("messages", [
    [],
    [("user", "Q")],
    [("assistant", "A"), ("user", "Q")],
    [("user", "Q"), ("user", "Q2")],
    [("system", "Guide")],
])
def test_validator_reports_invalid_message_sequences(messages: list[tuple[str, str]]) -> None:
    issues = SampleValidator().validate(sample(*messages))
    assert issues
    assert all(issue.severity == "error" for issue in issues)


def test_validator_reports_empty_content_and_invalid_role() -> None:
    invalid = sample(("user", "  "), ("assistant", "A"))
    invalid.messages[1].role = "tool"

    rules = {issue.rule for issue in SampleValidator().validate(invalid)}

    assert "empty_content" in rules
    assert "invalid_role" in rules


def test_validator_reports_mutated_message_structure() -> None:
    invalid = sample(("user", "Q"), ("assistant", "A"))
    invalid.messages = [{"role": "user", "content": "Q"}]

    issues = SampleValidator().validate(invalid)

    assert [issue.rule for issue in issues] == ["invalid_structure"]
