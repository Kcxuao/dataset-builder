"""Validate message structure and lossless target format support."""

from dataset_builder.models import ExportFormat, IssueSeverity, Message, TrainingSample, ValidationIssue

ALLOWED_ROLES = {"system", "user", "assistant"}


class SampleValidator:
    def validate(
        self,
        sample: TrainingSample,
        target_format: ExportFormat | None = None,
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []

        def add(rule: str, message: str) -> None:
            issues.append(ValidationIssue(
                sample_id=sample.id, rule=rule, severity=IssueSeverity.ERROR, message=message
            ))

        if not sample.messages:
            add("empty_messages", "Sample has no messages")
            return issues
        if any(not isinstance(message, Message) for message in sample.messages):
            add("invalid_structure", "Sample messages must contain Message objects")
            return issues

        roles = [str(message.role) for message in sample.messages]
        for index, (role, message) in enumerate(zip(roles, sample.messages, strict=True)):
            if role not in ALLOWED_ROLES:
                add("invalid_role", f"Message {index} has unsupported role {role!r}")
            if not message.content.strip():
                add("empty_content", f"Message {index} is empty")

        expected = "user"
        for index, role in enumerate(roles):
            if index == 0 and role == "system":
                continue
            if role != expected:
                add("message_order", f"Message {index} must have role {expected}")
                break
            expected = "assistant" if expected == "user" else "user"
        if expected != "user" or "assistant" not in roles:
            add("message_order", "Conversation must end with an assistant message")

        if target_format == ExportFormat.ALPACA and roles != ["user", "assistant"]:
            add("formatter_incompatible", "Alpaca requires exactly one user and one assistant message")
        return issues
