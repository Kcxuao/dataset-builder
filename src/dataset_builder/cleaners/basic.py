"""Normalize content, reject empty or oversized samples, and detect exact duplicates."""

import hashlib
import json
import unicodedata
from dataclasses import dataclass
from uuid import UUID

from dataset_builder.models import IssueSeverity, TrainingSample, ValidationIssue, utc_now


def normalize_content(content: str) -> str:
    return unicodedata.normalize("NFC", content.strip())


def content_hash(sample: TrainingSample) -> str:
    payload = [[str(message.role), normalize_content(message.content)] for message in sample.messages]
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass
class CleanResult:
    accepted: list[TrainingSample]
    rejected: list[TrainingSample]
    issues: list[ValidationIssue]


class BasicCleaner:
    def __init__(self, max_message_length: int = 10000) -> None:
        if max_message_length < 1:
            raise ValueError("max_message_length must be positive")
        self.max_message_length = max_message_length

    def clean(
        self,
        samples: list[TrainingSample],
        existing_hashes: set[tuple[UUID, str]] | None = None,
    ) -> CleanResult:
        seen = set(existing_hashes or ())
        result = CleanResult(accepted=[], rejected=[], issues=[])
        for original in samples:
            sample = original.model_copy(deep=True)
            for message in sample.messages:
                message.content = normalize_content(message.content)
            sample.updated_at = utc_now()
            sample.content_hash = content_hash(sample)
            problems: list[tuple[str, str]] = []
            if not sample.messages:
                problems.append(("empty_messages", "Sample has no messages"))
            for index, message in enumerate(sample.messages):
                if not message.content:
                    problems.append(("empty_content", f"Message {index} is empty"))
                elif len(message.content) > self.max_message_length:
                    problems.append(("content_too_long", f"Message {index} exceeds the length limit"))
            key = (sample.project_id, sample.content_hash)
            if not problems and key in seen:
                problems.append(("duplicate_content", "Sample duplicates normalized content in this project"))
            if problems:
                result.rejected.append(sample)
                result.issues.extend(
                    ValidationIssue(sample_id=sample.id, rule=rule, severity=IssueSeverity.ERROR, message=message)
                    for rule, message in problems
                )
            else:
                result.accepted.append(sample)
                seen.add(key)
        return result
