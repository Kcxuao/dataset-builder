"""Alpaca and ShareGPT output mapping without database dependencies."""

from typing import Protocol

from dataset_builder.models import ExportFormat, TrainingSample, ValidationIssue
from dataset_builder.validators import SampleValidator


class FormatError(ValueError):
    def __init__(self, issues: list[ValidationIssue]) -> None:
        self.issues = issues
        super().__init__("; ".join(issue.message for issue in issues))


class Formatter(Protocol):
    def format(self, sample: TrainingSample) -> dict[str, object]: ...


class AlpacaFormatter:
    def format(self, sample: TrainingSample) -> dict[str, object]:
        issues = SampleValidator().validate(sample, ExportFormat.ALPACA)
        if issues:
            raise FormatError(issues)
        return {
            "instruction": sample.messages[0].content,
            "input": "",
            "output": sample.messages[1].content,
        }


class ShareGPTFormatter:
    ROLE_MAP = {"system": "system", "user": "human", "assistant": "gpt"}

    def format(self, sample: TrainingSample) -> dict[str, object]:
        issues = SampleValidator().validate(sample, ExportFormat.SHAREGPT)
        if issues:
            raise FormatError(issues)
        return {
            "conversations": [
                {"from": self.ROLE_MAP[str(message.role)], "value": message.content}
                for message in sample.messages
            ]
        }
